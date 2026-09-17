/**
 * OAuth 2.1 で保護した「社内ドキュメント検索」MCP サーバーの起動口
 *
 * 背面で起動:
 *   docker compose exec -d node sh -c 'npx tsx src/session12/serve-protected.ts > /tmp/protected.log 2>&1'
 * ❌ aud 検証を外した Bad 実装で起動（10 節の実験専用）:
 *   docker compose exec -d -e MCP_AUTH_SKIP_AUD=on node \
 *     sh -c 'npx tsx src/session12/serve-protected.ts > /tmp/protected.log 2>&1'
 * 停止:
 *   docker compose exec node sh -c 'kill $(cat /tmp/mcp-protected.pid)'
 *
 * 環境変数
 *   MCP_HTTP_HOST / MCP_HTTP_PORT  待ち受け（既定 127.0.0.1 / 3939）
 *   MCP_AS_ISSUER                  信頼する認可サーバー（既定 http://127.0.0.1:9100）
 *   MCP_AS_JWKS_URI                公開鍵の所在（既定 <issuer>/jwks）
 *   MCP_RESOURCE                   このサーバーの識別子（既定 http://127.0.0.1:<port>/mcp）
 *   MCP_AUTH_SKIP_AUD=on           ❌ aud 検証を外す（実験専用・本番禁止）
 *   DOCSEARCH_ROOT                 検索対象ディレクトリ（mid01 の設定をそのまま使う）
 */
import { unlinkSync, writeFileSync } from "node:fs";
import http from "node:http";

import { resolveDocsRoot } from "../mid01/config.js";
import { createMcpHttpEndpoint } from "../session07/http-server.js";
import { resolveTrustPolicy } from "../session07/origin.js";
import { authLog, protectWithOAuth } from "./auth-middleware.js";
import { createProtectedServerFactory } from "./server-factory.js";
import { createTokenVerifier } from "./token-verifier.js";

const PID_FILE = "/tmp/mcp-protected.pid";
const ENDPOINT = "/mcp";

const host = process.env["MCP_HTTP_HOST"] ?? "127.0.0.1";
const port = Number(process.env["MCP_HTTP_PORT"] ?? "3939");
const issuer = process.env["MCP_AS_ISSUER"] ?? "http://127.0.0.1:9100";
const jwksUri = process.env["MCP_AS_JWKS_URI"] ?? `${issuer}/jwks`;
/**
 * このサーバーの識別子。クライアントが token 要求時に resource として送る値と、
 * トークンの aud と、ここが 3 つとも一致していなければ通りません。
 * 「URL の表記が 1 文字違う」で全部落ちるので、1 か所で決めて配ります。
 */
const resource =
  process.env["MCP_RESOURCE"] ??
  `http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${port}${ENDPOINT}`;
const skipAudience = process.env["MCP_AUTH_SKIP_AUD"] === "on";

const docsRoot = resolveDocsRoot([]);
const trust = resolveTrustPolicy(process.env, port);

const verifier = createTokenVerifier({ issuer, audience: resource, jwksUri, skipAudience });

// セッション7 の HTTP 層。ファイルは 1 行も変更していない
const mcp = createMcpHttpEndpoint({
  serverFactory: createProtectedServerFactory({ docsRoot }),
  endpoint: ENDPOINT,
  trust,
});

// その外側に認証層をかぶせる
const listener = protectWithOAuth({
  inner: mcp.listener,
  verifier,
  resource,
  authorizationServers: [issuer],
  endpoint: ENDPOINT,
  trust,
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

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
authLog(`待ち受け開始: http://${host}:${port}${ENDPOINT}（docsRoot=${docsRoot}）`);
authLog(`resource（＝要求する aud）: ${resource}`);
authLog(`信頼する認可サーバー: ${issuer} / JWKS: ${jwksUri}`);
authLog(`aud 検証: ${skipAudience ? "❌ 無効（実験用。本番では絶対に無効化しない）" : "有効"}`);
authLog(`PID ${process.pid}（${PID_FILE}）`);

let shuttingDown = false;

async function shutdown(signal: string): Promise<void> {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  authLog(`${signal} を受け取りました。セッションを閉じて終了します`);
  await mcp.closeAll();
  httpServer.closeAllConnections();
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));
  try {
    unlinkSync(PID_FILE);
  } catch {
    // すでに消えていてもよい
  }
  process.exit(0);
}

process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
