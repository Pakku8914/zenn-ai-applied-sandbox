/**
 * 社内ドキュメント検索サーバーを Streamable HTTP で公開するエントリーポイント
 *
 * 前面で起動:
 *   docker compose exec node npx tsx src/session07/serve-http.ts
 * 背面で起動（実験用。ログはファイルへ）:
 *   docker compose exec -d node sh -c 'npx tsx src/session07/serve-http.ts > /tmp/http.log 2>&1'
 * 停止:
 *   docker compose exec node sh -c 'kill $(cat /tmp/mcp-http.pid)'
 *
 * 環境変数
 *   MCP_HTTP_HOST       待ち受けアドレス（既定 127.0.0.1）
 *   MCP_HTTP_PORT       待ち受けポート（既定 3939）
 *   MCP_HTTP_JSON=on    SSE ではなく application/json で応答する
 *   MCP_TRUST_CHECK=off Origin / Host 検証を外す（実験用・本番禁止）
 *   MCP_MAX_SESSIONS    同時セッション数の上限（既定 32）
 *   DOCSEARCH_ROOT      検索対象ディレクトリ（mid01 の設定をそのまま使う）
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { resolveDocsRoot } from "../mid01/config.js";
import { createDocSearchServer } from "../mid01/create-server.js";
import { DEFAULT_HOST, DEFAULT_PORT, log, startHttpServer } from "./http-server.js";
import { resolveTrustPolicy } from "./origin.js";

const PID_FILE = "/tmp/mcp-http.pid";

const host = process.env["MCP_HTTP_HOST"] ?? DEFAULT_HOST;
const port = Number(process.env["MCP_HTTP_PORT"] ?? String(DEFAULT_PORT));
const maxSessions = Number(process.env["MCP_MAX_SESSIONS"] ?? "32");
// argv は使わない（tsx の引数と混ざるため）。差し替えは DOCSEARCH_ROOT で行う
const docsRoot = resolveDocsRoot([]);
const trust = resolveTrustPolicy(process.env, port);

const running = await startHttpServer({
  // ★ ここが今章の主題。mid01 のファクトリをそのまま渡すだけ
  serverFactory: () => createDocSearchServer({ docsRoot }),
  host,
  port,
  trust,
  maxSessions,
  jsonResponse: process.env["MCP_HTTP_JSON"] === "on",
});

writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");

log(`待ち受け開始: http://${host}:${port}${running.endpoint}（docsRoot=${docsRoot}）`);
log(`Origin 検証: ${trust.enabled ? "有効" : "無効（実験用）"} / 許可 Origin: ${trust.allowedOrigins.join(", ")}`);
log(`応答形式: ${process.env["MCP_HTTP_JSON"] === "on" ? "application/json" : "text/event-stream"}`);
log(`PID ${process.pid}（${PID_FILE}）。停止するには kill ${process.pid}`);

let shuttingDown = false;

async function shutdown(signal: string): Promise<void> {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  log(`${signal} を受け取りました。セッションを閉じて終了します`);
  await running.close();
  try {
    unlinkSync(PID_FILE);
  } catch {
    // すでに消えていてもよい
  }
  process.exit(0);
}

// stdio と違い、HTTP サーバーは自分で終了処理を書く必要がある
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
