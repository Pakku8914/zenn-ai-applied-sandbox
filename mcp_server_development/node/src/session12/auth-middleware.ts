/**
 * OAuth 2.1 の受付 ―― Protected Resource Metadata の公開とトークン検証
 *
 * セッション7 の `createMcpHttpEndpoint` が返す listener を包みます。
 * セッション7 の dispatch() に置いたコメント
 *   「★ セッション12（OAuth 2.1）では、この位置にアクセストークンの検証を 1 段足す」
 * と同じ順序（パス判定 → Origin/Host → トークン → セッション）になるように、
 * この層でも Origin/Host を先に見ています（8 節で理由を説明します）。
 */
import http from "node:http";

import {
  type TrustPolicy,
  createTrustPolicy,
  firstHeader,
  verifyRequestTrust,
} from "../session07/origin.js";
import { SCOPE_DOCS_READ, SUPPORTED_SCOPES, runWithAuth } from "./scopes.js";
import type { TokenVerifier, VerifyFailure } from "./token-verifier.js";

/**
 * RFC 9728。リソース識別子にパスがある場合は、well-known の「後ろ」にそのパスを足す。
 *   resource = http://127.0.0.1:3939/mcp
 *   → /.well-known/oauth-protected-resource/mcp
 * 互換のためパス無しの位置でも同じ内容を返します（仕様改訂で変わりうる箇所です）。
 */
export function protectedResourceMetadataPaths(endpoint: string): readonly string[] {
  const base = "/.well-known/oauth-protected-resource";
  return endpoint === "" || endpoint === "/" ? [base] : [base, `${base}${endpoint}`];
}

export type ProtectOptions = {
  /** セッション7 の createMcpHttpEndpoint().listener */
  readonly inner: http.RequestListener;
  readonly verifier: TokenVerifier;
  /** このサーバー自身の識別子。トークンの aud はこれと完全一致しなければならない */
  readonly resource: string;
  readonly authorizationServers: readonly string[];
  readonly endpoint?: string;
  readonly trust?: TrustPolicy;
  /** このリソースに触るための最低スコープ */
  readonly baseScope?: string;
};

type Challenge = {
  readonly status: number;
  readonly error?: string;
  /** ⚠️ ヘッダーには ASCII しか置けない。日本語を入れると ERR_INVALID_CHAR で落ちる */
  readonly description: string;
  readonly scope?: string;
};

/** 検証失敗の理由 → 返すべき HTTP の応答。理由コードはログ用、文面は無情報 */
const CHALLENGES: Readonly<Record<VerifyFailure, Challenge>> = {
  missing_token: { status: 401, description: "An access token is required" },
  malformed_header: {
    status: 401,
    error: "invalid_request",
    description: "The Authorization header is malformed",
  },
  malformed_token: { status: 401, error: "invalid_token", description: "The token is malformed" },
  unsupported_alg: {
    status: 401,
    error: "invalid_token",
    description: "The signature algorithm is not allowed",
  },
  embedded_key: {
    status: 401,
    error: "invalid_token",
    description: "The token header carries key material",
  },
  unknown_kid: { status: 401, error: "invalid_token", description: "The signing key is unknown" },
  bad_signature: { status: 401, error: "invalid_token", description: "The signature is invalid" },
  issuer_mismatch: { status: 401, error: "invalid_token", description: "The issuer is not trusted" },
  expired: { status: 401, error: "invalid_token", description: "The access token is expired" },
  not_yet_valid: { status: 401, error: "invalid_token", description: "The token is not valid yet" },
  audience_mismatch: {
    status: 401,
    error: "invalid_token",
    description: "The token was not issued for this resource",
  },
  jwks_unavailable: {
    status: 503,
    error: "temporarily_unavailable",
    description: "Signing keys are temporarily unavailable",
  },
};

export function protectWithOAuth(options: ProtectOptions): http.RequestListener {
  const endpoint = options.endpoint ?? "/mcp";
  const trust = options.trust ?? createTrustPolicy();
  const baseScope = options.baseScope ?? SCOPE_DOCS_READ;
  const metadataPaths = protectedResourceMetadataPaths(endpoint);
  const canonicalPath = metadataPaths[metadataPaths.length - 1] ?? metadataPaths[0] ?? "/";
  const metadataUrl = `${new URL(options.resource).origin}${canonicalPath}`;
  const metadataBody = JSON.stringify({
    resource: options.resource,
    authorization_servers: [...options.authorizationServers],
    scopes_supported: [...SUPPORTED_SCOPES],
    bearer_methods_supported: ["header"],
    resource_name: "社内ドキュメント検索 MCP サーバー",
  });

  async function handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const pathname = new URL(req.url ?? "/", "http://placeholder").pathname;

    // ① メタデータは認証の前に置く。401 を受けた人がここを読みに来るのだから、
    //    ここを保護したら発見フローが永久に閉じる（鶏と卵になる）
    if (metadataPaths.includes(pathname)) {
      if (req.method !== "GET") {
        res.writeHead(405, { allow: "GET", "content-type": "application/json" });
        res.end(JSON.stringify({ error: "method_not_allowed" }));
        return;
      }
      res.writeHead(200, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(metadataBody),
        // 変わらない情報なのでキャッシュさせる。毎リクエスト取りに来られると無駄
        "cache-control": "public, max-age=3600",
      });
      res.end(metadataBody);
      return;
    }

    // ② Origin / Host（セッション7 の受付）。下流でも走るが多層防御として残す
    const verdict = verifyRequestTrust(req.headers, trust);
    if (!verdict.ok) {
      authLog(`拒否（${verdict.reason}）: origin=${firstHeader(req.headers.origin) ?? "(なし)"}`);
      sendJson(res, 403, -32003, verdict.detail);
      return;
    }

    // ③ アクセストークンの検証（セッション7 が「ここに 1 段足す」と書いた位置）
    const outcome = await options.verifier.verify(firstHeader(req.headers.authorization));
    if (!outcome.ok) {
      // 未知のパスでも 404 を返さない。認証を通す前に「存在するパス」を教えないため
      authLog(`認証失敗（${outcome.reason}）: ${req.method ?? "?"} ${pathname}`);
      sendChallenge(res, CHALLENGES[outcome.reason], metadataUrl);
      return;
    }
    const context = outcome.context;

    // ④ ベーススコープ。ここは「接続してよいか」の判定なので HTTP 層で 403 を返す
    if (!context.scopes.includes(baseScope)) {
      authLog(
        `認可失敗（insufficient_scope）: sub=${context.subject} scopes=[${context.scopes.join(" ")}]` +
          ` token=${context.fingerprint}`,
      );
      sendChallenge(
        res,
        {
          status: 403,
          error: "insufficient_scope",
          description: "The token lacks the required scope",
          scope: baseScope,
        },
        metadataUrl,
      );
      return;
    }

    authLog(
      `許可: sub=${context.subject} client=${context.clientId ?? "-"}` +
        ` scopes=[${context.scopes.join(" ")}] token=${context.fingerprint}`,
    );
    // ⑤ 認証文脈を非同期スコープに載せて下流（MCP 層）へ渡す
    runWithAuth(context, () => options.inner(req, res));
  }

  return (req, res) => {
    handle(req, res).catch((error: unknown) => {
      authLog(`認証層で未処理の例外: ${error instanceof Error ? error.message : String(error)}`);
      if (res.headersSent) {
        res.end();
        return;
      }
      sendJson(res, 500, -32603, "サーバー内部エラーです。");
    });
  };
}

function sendChallenge(res: http.ServerResponse, challenge: Challenge, metadataUrl: string): void {
  // WWW-Authenticate の組み立て。auth-scheme のあとにパラメータをカンマで並べる
  const parts = [`Bearer resource_metadata="${metadataUrl}"`];
  if (challenge.error !== undefined) {
    parts.push(`error="${challenge.error}"`);
  }
  parts.push(`error_description="${challenge.description}"`);
  if (challenge.scope !== undefined) {
    parts.push(`scope="${challenge.scope}"`);
  }
  const message =
    challenge.status === 403
      ? "このトークンには必要な権限（スコープ）がありません。必要なスコープは WWW-Authenticate ヘッダーを参照してください。"
      : challenge.status === 503
        ? "署名鍵を取得できないため、いまトークンを検証できません。しばらく待って再試行してください。"
        : "有効なアクセストークンが必要です。WWW-Authenticate ヘッダーの resource_metadata から認可サーバーを見つけ、トークンを取得してください。";
  const body = JSON.stringify({
    jsonrpc: "2.0",
    error: { code: challenge.status === 403 ? -32005 : -32004, message },
    id: null,
  });
  const headers: Record<string, string> = {
    "www-authenticate": parts.join(", "),
    "content-type": "application/json",
    "content-length": String(Buffer.byteLength(body)),
  };
  if (challenge.status === 503) {
    headers["retry-after"] = "5";
  }
  res.writeHead(challenge.status, headers);
  res.end(body);
}

function sendJson(res: http.ServerResponse, status: number, code: number, message: string): void {
  const body = JSON.stringify({ jsonrpc: "2.0", error: { code, message }, id: null });
  res.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

export function authLog(message: string): void {
  console.error(`[mcp-auth] ${message}`);
}
