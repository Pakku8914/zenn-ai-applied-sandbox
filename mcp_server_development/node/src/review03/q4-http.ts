/**
 * 問題4 の解答 ―― Streamable HTTP の最小エンドポイント
 *
 * セッション7 の http-server.ts を復習として書き直した縮小版です
 * （再開可能性の EventStore は省いています）。
 *
 *   ① ドメイン層      : docsearch-lite.ts     MCP を知らない
 *   ② MCP 層          : create-server-lite.ts トランスポートを知らない
 *   ③ トランスポート層: このファイル          ドメインを知らない
 *
 * HTTP では stdout は通信路ではないので console.log でも電文は壊れません。
 * それでもログは stderr に統一します（同じログ関数を stdio 版と共用できるようにするため）。
 */
import { randomUUID } from "node:crypto";
import http from "node:http";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

export const DEFAULT_HOST = "127.0.0.1";
export const DEFAULT_PORT = 3939;
export const DEFAULT_ENDPOINT = "/mcp";
/** POST 本文の上限。無制限にするとメモリ枯渇攻撃を受ける */
export const MAX_BODY_BYTES = 1024 * 1024;
/** 同時セッション数の上限。1 セッションが 1 つのサーバー実体を抱えるので上限が必要 */
export const DEFAULT_MAX_SESSIONS = 4;

export type TrustPolicy = {
  /** false にすると検証を丸ごと外す（実験用。本番では絶対に false にしない） */
  readonly enabled: boolean;
  readonly allowedOrigins: readonly string[];
  readonly allowedHosts: readonly string[];
};

export type HttpEndpointOptions = {
  /** セッションごとに新しいサーバー定義を作る関数 */
  readonly serverFactory: () => McpServer;
  readonly host?: string;
  readonly port?: number;
  readonly endpoint?: string;
  readonly trust?: TrustPolicy;
  readonly maxSessions?: number;
  /** true にすると SSE ではなく application/json で応答する（問題7 で使う） */
  readonly jsonResponse?: boolean;
};

export type RunningEndpoint = {
  readonly host: string;
  readonly port: number;
  readonly endpoint: string;
  sessionCount(): number;
  close(): Promise<void>;
};

export function log(message: string): void {
  console.error(`[review03-http] ${message}`);
}

export function resolveTrustPolicy(
  port: number,
  env: NodeJS.ProcessEnv = process.env,
): TrustPolicy {
  return {
    // 既定は有効。off と明示的に書いたときだけ無効になる
    enabled: env["MCP_TRUST_CHECK"] !== "off",
    allowedOrigins: ["http://127.0.0.1:6274", "http://localhost:6274"],
    allowedHosts: [`127.0.0.1:${port}`, `localhost:${port}`],
  };
}

type TrustFailure = "origin_not_allowed" | "host_not_allowed";

type TrustResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: TrustFailure; readonly detail: string };

/** ヘッダーは配列で来ることがある（同名ヘッダーが複数ある場合） */
function firstHeader(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function verifyRequestTrust(headers: http.IncomingHttpHeaders, policy: TrustPolicy): TrustResult {
  if (!policy.enabled) {
    return { ok: true };
  }
  // Origin が無い＝ブラウザ以外（SDK クライアント・Inspector CLI・自作スクリプト）。
  // ブラウザは必ず付け、JavaScript から偽装できないので、「無い」ことが判断材料になる
  const origin = firstHeader(headers.origin);
  if (origin !== undefined && origin !== "" && !policy.allowedOrigins.includes(origin)) {
    return {
      ok: false,
      reason: "origin_not_allowed",
      detail: "この Origin からのリクエストは許可されていません。",
    };
  }
  // Host も見る（多層防御）。DNS リバインディングでは Host が攻撃者のドメインになる
  const host = firstHeader(headers.host);
  if (host !== undefined && host !== "" && !policy.allowedHosts.includes(host)) {
    return {
      ok: false,
      reason: "host_not_allowed",
      detail: "この Host 名では受け付けていません。",
    };
  }
  return { ok: true };
}

type BodyResult =
  | { readonly ok: true; readonly value: unknown }
  | { readonly ok: false; readonly status: number; readonly message: string };

async function readJsonBody(req: http.IncomingMessage): Promise<BodyResult> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
    total += buffer.byteLength;
    if (total > MAX_BODY_BYTES) {
      // 読み切らずに切断する。読み切ると上限の意味がない
      req.destroy();
      return {
        ok: false,
        status: 413,
        message: `本文が上限（${MAX_BODY_BYTES} バイト）を超えました。`,
      };
    }
    chunks.push(buffer);
  }
  try {
    return { ok: true, value: JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown };
  } catch {
    return { ok: false, status: 400, message: "本文が JSON として解釈できません。" };
  }
}

function errorBody(code: number, message: string): string {
  // id は null。どのリクエストへの応答か特定できない失敗なので
  return JSON.stringify({ jsonrpc: "2.0", error: { code, message }, id: null });
}

function sendError(
  res: http.ServerResponse,
  status: number,
  code: number,
  message: string,
  extraHeaders: http.OutgoingHttpHeaders = {},
): void {
  const payload = errorBody(code, message);
  res.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(payload),
    ...extraHeaders,
  });
  res.end(payload);
}

/** 単体でも配列（バッチ）でも initialize が含まれているかを判定する */
function containsInitialize(body: unknown): boolean {
  const messages: unknown[] = Array.isArray(body) ? body : [body];
  return messages.some(
    (message) =>
      typeof message === "object" &&
      message !== null &&
      (message as { method?: unknown }).method === "initialize",
  );
}

export async function startHttpEndpoint(options: HttpEndpointOptions): Promise<RunningEndpoint> {
  const host = options.host ?? DEFAULT_HOST;
  const port = options.port ?? DEFAULT_PORT;
  const endpoint = options.endpoint ?? DEFAULT_ENDPOINT;
  const trust = options.trust ?? resolveTrustPolicy(port);
  const maxSessions = options.maxSessions ?? DEFAULT_MAX_SESSIONS;

  type Session = {
    readonly transport: StreamableHTTPServerTransport;
    readonly server: McpServer;
  };
  const sessions = new Map<string, Session>();

  async function openSession(): Promise<Session> {
    // セッション ID を先に自分で作る。トランスポートの採番を待たないので、
    // 初期化処理中に届く後続リクエストでも取り違えが起きない
    const id = randomUUID();
    const transport = new StreamableHTTPServerTransport({
      // 推測できない値であることが必須。連番は禁止（他人のセッションを乗っ取れる）
      sessionIdGenerator: () => id,
      enableJsonResponse: options.jsonResponse ?? false,
    });
    const server = options.serverFactory();
    const session: Session = { transport, server };

    // 破棄の経路を 1 か所に集める（DELETE・接続断・close() のどれでもここを通る）
    transport.onclose = () => {
      if (sessions.delete(id)) {
        log(`セッション破棄: ${id}（残り ${sessions.size} 件）`);
      }
      void server.close();
    };

    await server.connect(transport);
    sessions.set(id, session);
    log(`セッション発行: ${id}（同時 ${sessions.size} 件）`);
    return session;
  }

  async function handlePost(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    sessionId: string | undefined,
  ): Promise<void> {
    const parsed = await readJsonBody(req);
    if (!parsed.ok) {
      sendError(res, parsed.status, -32700, parsed.message);
      return;
    }

    if (sessionId !== undefined) {
      const session = sessions.get(sessionId);
      if (session === undefined) {
        // 「知らないセッション ID」は 404。クライアントは initialize からやり直す
        sendError(
          res,
          404,
          -32001,
          "セッションが見つかりません。initialize からやり直してください。",
        );
        return;
      }
      await session.transport.handleRequest(req, res, parsed.value);
      return;
    }

    if (!containsInitialize(parsed.value)) {
      sendError(
        res,
        400,
        -32600,
        "Mcp-Session-Id ヘッダーがありません。最初のリクエストは initialize です。",
      );
      return;
    }
    if (sessions.size >= maxSessions) {
      // 上限が無いと、initialize を投げ続けるだけでメモリを食い潰せる
      sendError(
        res,
        503,
        -32002,
        "同時セッション数の上限に達しました。しばらく待って再試行してください。",
      );
      return;
    }

    const session = await openSession();
    await session.transport.handleRequest(req, res, parsed.value);
  }

  /** GET（サーバー起点ストリーム）と DELETE（破棄）はどちらも既存セッションが前提 */
  async function handleWithSession(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    sessionId: string | undefined,
  ): Promise<void> {
    if (sessionId === undefined) {
      sendError(res, 400, -32600, "Mcp-Session-Id ヘッダーが必要です。");
      return;
    }
    const session = sessions.get(sessionId);
    if (session === undefined) {
      sendError(res, 404, -32001, "セッションが見つかりません。");
      return;
    }
    await session.transport.handleRequest(req, res);
  }

  async function dispatch(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    // 公開するのは 1 エンドポイントだけ。それ以外は 404 で即断る
    const pathname = new URL(req.url ?? "/", "http://placeholder").pathname;
    if (pathname !== endpoint) {
      sendError(res, 404, -32600, `このサーバーが公開しているのは ${endpoint} だけです。`);
      return;
    }

    const verdict = verifyRequestTrust(req.headers, trust);
    if (!verdict.ok) {
      // 理由は機械可読な値でログに残す。入力値そのものは応答に含めない
      log(
        `拒否（${verdict.reason}）: origin=${firstHeader(req.headers.origin) ?? "(なし)"}` +
          ` host=${firstHeader(req.headers.host) ?? "(なし)"}`,
      );
      sendError(res, 403, -32003, verdict.detail);
      return;
    }

    // ★ セッション12（OAuth 2.1）では、この位置にアクセストークンの検証を 1 段足す

    const sessionId = firstHeader(req.headers["mcp-session-id"]);
    switch (req.method) {
      case "POST":
        await handlePost(req, res, sessionId);
        return;
      case "GET":
      case "DELETE":
        await handleWithSession(req, res, sessionId);
        return;
      default:
        sendError(res, 405, -32600, `${req.method ?? "?"} は使えません。`, {
          allow: "POST, GET, DELETE",
        });
    }
  }

  const listener: http.RequestListener = (req, res) => {
    // リスナーは同期関数。非同期の例外は自分で受け止める（未処理の拒否でプロセスが落ちる）
    dispatch(req, res).catch((error: unknown) => {
      log(`未処理の例外: ${error instanceof Error ? error.message : String(error)}`);
      if (res.headersSent) {
        res.end();
      } else {
        sendError(res, 500, -32603, "サーバー内部エラーです。");
      }
    });
  };

  const httpServer = http.createServer(listener);
  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error): void => reject(error);
    httpServer.once("error", onError);
    httpServer.listen(port, host, () => {
      httpServer.removeListener("error", onError);
      resolve();
    });
  });

  return {
    host,
    port,
    endpoint,
    sessionCount: () => sessions.size,
    close: async () => {
      await Promise.all([...sessions.values()].map((session) => session.transport.close()));
      sessions.clear();
      // SSE で開いたままの接続は close() だけでは終わらないので明示的に切る
      httpServer.closeAllConnections();
      await new Promise<void>((resolve) => {
        httpServer.close(() => resolve());
      });
    },
  };
}
