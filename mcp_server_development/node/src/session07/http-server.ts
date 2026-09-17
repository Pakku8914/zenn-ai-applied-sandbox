/**
 * Streamable HTTP トランスポート ―― HTTP 層の実装
 *
 * 追加依存はありません（Node.js 22 標準の node:http だけ）。
 * mid01 のサーバー定義（create-server.ts）は読み取り専用で使います。
 *
 *   ① ドメイン層      : mid01/domain/*         MCP を知らない
 *   ② MCP 層          : mid01/create-server.ts トランスポートを知らない
 *   ③ トランスポート層: このファイル            ドメインを知らない
 *
 * stdout について：HTTP では stdout は通信路ではないので console.log でも電文は
 * 壊れません。それでもログは stderr に統一します（13 節の dual.ts で、同じ
 * ログ出力コードを stdio 版と使い回せるようにするため）。
 */
import { randomUUID } from "node:crypto";
import http from "node:http";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  type EventStore,
  StreamableHTTPServerTransport,
} from "@modelcontextprotocol/sdk/server/streamableHttp.js";

import {
  type TrustPolicy,
  createTrustPolicy,
  firstHeader,
  verifyRequestTrust,
} from "./origin.js";

export const DEFAULT_HOST = "127.0.0.1";
export const DEFAULT_PORT = 3939;
export const DEFAULT_ENDPOINT = "/mcp";
/** POST 本文の上限。無制限にするとメモリ枯渇攻撃を受ける */
export const MAX_BODY_BYTES = 1024 * 1024;
/** 同時セッション数の上限。1 セッションが 1 つのサーバー実体を抱えるので上限が必要 */
export const MAX_SESSIONS = 32;

export type McpHttpOptions = {
  /** セッションごとに新しいサーバー定義を作る関数。mid01 のファクトリをそのまま渡す */
  readonly serverFactory: () => McpServer;
  readonly host?: string;
  readonly port?: number;
  readonly endpoint?: string;
  readonly trust?: TrustPolicy;
  readonly maxSessions?: number;
  /** 再開可能性（練習問題6）。渡すとイベント ID が振られ Last-Event-ID が使える */
  readonly eventStore?: EventStore;
  /** true にすると SSE ではなく application/json で応答する（9 節） */
  readonly jsonResponse?: boolean;
};

export type SessionInfo = {
  readonly id: string;
  readonly createdAt: number;
  readonly lastSeenAt: number;
};

export type McpHttpEndpoint = {
  readonly endpoint: string;
  readonly listener: http.RequestListener;
  sessions(): SessionInfo[];
  closeSession(id: string): Promise<boolean>;
  closeAll(): Promise<void>;
};

export type RunningHttpServer = McpHttpEndpoint & {
  readonly httpServer: http.Server;
  readonly host: string;
  readonly port: number;
  close(): Promise<void>;
};

type Session = {
  readonly id: string;
  readonly transport: StreamableHTTPServerTransport;
  readonly server: McpServer;
  readonly createdAt: number;
  /** アイドル判定に使う。練習問題9 の寿命管理がこの値を読む */
  lastSeenAt: number;
};

export function createMcpHttpEndpoint(options: McpHttpOptions): McpHttpEndpoint {
  const endpoint = options.endpoint ?? DEFAULT_ENDPOINT;
  const trust = options.trust ?? createTrustPolicy();
  const maxSessions = options.maxSessions ?? MAX_SESSIONS;
  const sessions = new Map<string, Session>();

  async function openSession(): Promise<Session> {
    // セッション ID を先に自分で作る。トランスポートの採番を待たないので、
    // 初期化の処理中に届く後続リクエストでも取り違えが起きない
    const id = randomUUID();
    const transport = new StreamableHTTPServerTransport({
      // 推測できない値であることが必須。連番は禁止（他人のセッションを乗っ取れる）
      sessionIdGenerator: () => id,
      enableJsonResponse: options.jsonResponse ?? false,
      eventStore: options.eventStore,
    });
    const server = options.serverFactory();
    const now = Date.now();
    const session: Session = { id, transport, server, createdAt: now, lastSeenAt: now };

    // 破棄の経路は 1 つに集める（DELETE・接続断・close() のどれでもここを通る）
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
      sendError(res, parsed.reason === "too_large" ? 413 : 400, -32700, parsed.message);
      return;
    }

    if (sessionId !== undefined) {
      const session = sessions.get(sessionId);
      if (session === undefined) {
        // 「知らないセッション ID」は 404。クライアントは initialize からやり直す
        sendError(res, 404, -32001, "セッションが見つかりません。initialize からやり直してください。");
        return;
      }
      session.lastSeenAt = Date.now();
      await session.transport.handleRequest(req, res, parsed.value);
      return;
    }

    if (!containsInitialize(parsed.value)) {
      sendError(res, 400, -32600, "Mcp-Session-Id ヘッダーがありません。最初のリクエストは initialize です。");
      return;
    }
    if (sessions.size >= maxSessions) {
      // 上限を設けないと、initialize を投げ続けるだけでメモリを食い潰せる
      sendError(res, 503, -32002, "同時セッション数の上限に達しました。しばらく待って再試行してください。");
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
    session.lastSeenAt = Date.now();
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
      log(
        `拒否（${verdict.reason}）: origin=${firstHeader(req.headers.origin) ?? "(なし)"}` +
          ` host=${firstHeader(req.headers.host) ?? "(なし)"}`,
      );
      sendError(res, 403, -32003, verdict.detail);
      return;
    }

    // ★ セッション12（OAuth 2.1）では、この位置に「アクセストークンの検証」を 1 段足す

    const sessionId = firstHeader(req.headers["mcp-session-id"]);
    switch (req.method) {
      case "POST":
        await handlePost(req, res, sessionId);
        return;
      case "GET":
      case "DELETE":
        await handleWithSession(req, res, sessionId);
        return;
      default: {
        res.writeHead(405, { allow: "POST, GET, DELETE", "content-type": "application/json" });
        res.end(errorBody(-32600, `${req.method ?? "?"} は使えません。`));
      }
    }
  }

  const listener: http.RequestListener = (req, res) => {
    // ハンドラは同期関数なので、例外を必ず自分で受け止める（未処理拒否でプロセスが落ちる）
    dispatch(req, res).catch((error: unknown) => {
      log(`未処理の例外: ${error instanceof Error ? error.message : String(error)}`);
      if (res.headersSent) {
        res.end();
      } else {
        sendError(res, 500, -32603, "サーバー内部エラーです。");
      }
    });
  };

  return {
    endpoint,
    listener,
    sessions: () =>
      [...sessions.values()].map(({ id, createdAt, lastSeenAt }) => ({ id, createdAt, lastSeenAt })),
    closeSession: async (id) => {
      const session = sessions.get(id);
      if (session === undefined) {
        return false;
      }
      // transport.close() が onclose を呼び、Map からの削除もそこで行われる
      await session.transport.close();
      return true;
    },
    closeAll: async () => {
      await Promise.all([...sessions.values()].map((session) => session.transport.close()));
      sessions.clear();
    },
  };
}

export async function startHttpServer(options: McpHttpOptions): Promise<RunningHttpServer> {
  const host = options.host ?? DEFAULT_HOST;
  const port = options.port ?? DEFAULT_PORT;
  const mcp = createMcpHttpEndpoint(options);
  const httpServer = http.createServer(mcp.listener);

  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error): void => reject(error);
    httpServer.once("error", onError);
    httpServer.listen(port, host, () => {
      httpServer.removeListener("error", onError);
      resolve();
    });
  });

  return {
    ...mcp,
    httpServer,
    host,
    port,
    close: async () => {
      await mcp.closeAll();
      // SSE で開いたままの接続は close() だけでは終わらないので明示的に切る
      httpServer.closeAllConnections();
      await new Promise<void>((resolve) => {
        httpServer.close(() => resolve());
      });
    },
  };
}

/** ステートレス版（練習問題7）でも使うので export しておく */
export type BodyResult =
  | { readonly ok: true; readonly value: unknown }
  | { readonly ok: false; readonly reason: "too_large" | "invalid_json"; readonly message: string };

export async function readJsonBody(req: http.IncomingMessage): Promise<BodyResult> {
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
        reason: "too_large",
        message: `本文が上限（${MAX_BODY_BYTES} バイト）を超えました。`,
      };
    }
    chunks.push(buffer);
  }
  try {
    return { ok: true, value: JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown };
  } catch {
    return { ok: false, reason: "invalid_json", message: "本文が JSON として解釈できません。" };
  }
}

export function sendError(
  res: http.ServerResponse,
  status: number,
  code: number,
  message: string,
): void {
  const payload = errorBody(code, message);
  res.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

export function log(message: string): void {
  console.error(`[mcp-http] ${message}`);
}

function errorBody(code: number, message: string): string {
  // id は null。どのリクエストへの応答か特定できない失敗なので
  return JSON.stringify({ jsonrpc: "2.0", error: { code, message }, id: null });
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
