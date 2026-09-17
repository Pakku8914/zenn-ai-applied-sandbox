/**
 * 認証付き Streamable HTTP サーバーの組み立て
 *
 * 層の重ね方（外側から）
 *   ① final/resource-metadata.ts   自分の Protected Resource Metadata
 *   ② session12/protectWithOAuth   Origin → トークン → ベーススコープ
 *   ③ 認証文脈のブリッジ            S12 の文脈 → final の AuthContext
 *   ④ session07/createMcpHttpEndpoint  Mcp-Session-Id
 *   ⑤ final/createWorkflowServer   ツール・リソース・プロンプト
 *
 * ★ session07 / session12 のファイルは 1 行も変更していません。
 */
import http from "node:http";

import { createMcpHttpEndpoint } from "../session07/http-server.js";
import { resolveTrustPolicy } from "../session07/origin.js";
import { protectWithOAuth } from "../session12/auth-middleware.js";
import { currentAuth as currentOauthAuth } from "../session12/scopes.js";
import { createTokenVerifier } from "../session12/token-verifier.js";
import { type AuthContext, SCOPE_READ, SUPPORTED_SCOPES, runWithAuth } from "./auth/scopes.js";
import { createWorkflowServer } from "./create-server.js";
import { createStore } from "./domain/workflow.js";
import { createAuditLogger } from "./observability/audit.js";
import { withResourceMetadata } from "./resource-metadata.js";
import { RESOURCE_NAME, SERVER_NAME } from "./version.js";

export type ServeOptions = {
  readonly host?: string;
  readonly port?: number;
  readonly endpoint?: string;
  readonly issuer: string;
  readonly jwksUri?: string;
  readonly resource?: string;
  readonly tenantId?: string;
  /** 監査ログのハッシュ鍵。環境変数で渡す（コードに書かない） */
  readonly auditPepper: string;
  /** ❌ 実験専用。true にすると aud 検証を飛ばす */
  readonly skipAudience?: boolean;
};

export type RunningServer = {
  readonly host: string;
  readonly port: number;
  readonly endpoint: string;
  readonly resource: string;
  readonly issuer: string;
  readonly jwksUri: string;
  readonly skipAudience: boolean;
  close(): Promise<void>;
};

/**
 * セッション12 の認証文脈を、この書籍の最終プロジェクトの型へ詰め替える。
 *
 * ★ ここを忘れると currentAuth() が常に undefined になり、
 *   HTTP は 200 なのに全ツールが forbidden になります（fail closed の副作用）。
 */
function bridgeAuth(inner: http.RequestListener, tenantId: string): http.RequestListener {
  return (req, res) => {
    const oauth = currentOauthAuth();
    if (oauth === undefined) {
      inner(req, res);
      return;
    }
    const context: AuthContext = {
      subject: oauth.subject,
      clientId: oauth.clientId,
      scopes: oauth.scopes,
      expiresAt: oauth.expiresAt,
      // 生のトークンは受け取らない。相関 ID だけを運ぶ
      tokenRef: oauth.fingerprint,
      tenantId,
    };
    runWithAuth(context, () => inner(req, res));
  };
}

export async function startProtectedServer(options: ServeOptions): Promise<RunningServer> {
  const host = options.host ?? "127.0.0.1";
  const port = options.port ?? 3939;
  const endpoint = options.endpoint ?? "/mcp";
  const issuer = options.issuer;
  const jwksUri = options.jwksUri ?? `${issuer}/jwks`;
  // リソース識別子は 1 か所で決めて配る。ここが 1 文字違うと aud 検証が全部落ちる
  const resource =
    options.resource ?? `http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${port}${endpoint}`;
  const tenantId = options.tenantId ?? "acme";
  const skipAudience = options.skipAudience ?? false;

  const trust = resolveTrustPolicy(process.env, port);
  // 申請データはプロセスで 1 つ。セッションごとに作り直さない
  const store = createStore();
  const audit = createAuditLogger({ server: SERVER_NAME, pepper: options.auditPepper });
  const verifier = createTokenVerifier({
    issuer,
    audience: resource,
    jwksUri,
    ...(skipAudience ? { skipAudience: true } : {}),
  });

  const mcp = createMcpHttpEndpoint({
    // セッションごとに新しいサーバー定義を作る。store と audit は共有する
    serverFactory: () => createWorkflowServer({ store, audit }),
    endpoint,
    trust,
  });

  const protectedListener = protectWithOAuth({
    inner: bridgeAuth(mcp.listener, tenantId),
    verifier,
    resource,
    authorizationServers: [issuer],
    endpoint,
    trust,
    baseScope: SCOPE_READ,
  });

  const listener = withResourceMetadata({
    inner: protectedListener,
    resource,
    authorizationServers: [issuer],
    scopesSupported: SUPPORTED_SCOPES,
    resourceName: RESOURCE_NAME,
    endpoint,
  });

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
    resource,
    issuer,
    jwksUri,
    skipAudience,
    close: async () => {
      await mcp.closeAll();
      httpServer.closeAllConnections();
      await new Promise<void>((resolve) => httpServer.close(() => resolve()));
    },
  };
}
