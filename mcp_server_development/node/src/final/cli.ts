#!/usr/bin/env node
/**
 * workflow-requests-mcp ― 実行可能エントリーポイント（package.json の bin から起動される）
 *
 *   workflow-requests-mcp --port 3939 --issuer http://127.0.0.1:9100
 *   AUDIT_PEPPER=... workflow-requests-mcp
 *
 * --help / --version は「サーバーではないモード」なので stdout に出してかまいません。
 * サーバーとして動き始めたあとは stderr にしか書きません。
 */
import { startProtectedServer } from "./serve-core.js";
import { PACKAGE_NAME, SERVER_VERSION } from "./version.js";

const HELP = `${PACKAGE_NAME} ${SERVER_VERSION}
社内申請ワークフローを扱う、OAuth 2.1 で保護された MCP サーバー（Streamable HTTP）です。

使い方:
  ${PACKAGE_NAME} [--host <addr>] [--port <n>] [--issuer <url>] [--resource <url>]

環境変数:
  AUDIT_PEPPER    監査ログのハッシュ鍵（必須）
  MCP_HTTP_HOST   待ち受けアドレス（既定 127.0.0.1）
  MCP_HTTP_PORT   待ち受けポート（既定 3939）
  MCP_AS_ISSUER   信頼する認可サーバー（既定 http://127.0.0.1:9100）
  MCP_RESOURCE    このサーバーの識別子（既定 http://<host>:<port>/mcp）

ホストからの接続例（Streamable HTTP に対応したホスト）:
  { "type": "http", "url": "http://127.0.0.1:3939/mcp" }
`;

function flag(name: string): string | undefined {
  const index = process.argv.indexOf(`--${name}`);
  if (index < 0) return undefined;
  const value = process.argv[index + 1];
  return value === undefined || value.startsWith("--") ? undefined : value;
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(HELP);
  process.exit(0);
}
if (process.argv.includes("--version") || process.argv.includes("-v")) {
  console.log(`${PACKAGE_NAME} ${SERVER_VERSION}`);
  process.exit(0);
}

// ★ 既定値を持たせない。設定漏れは「弱い鍵で動く」ではなく「起動しない」にする
const auditPepper = process.env["AUDIT_PEPPER"];
if (auditPepper === undefined || auditPepper.length < 16) {
  console.error(
    "[fatal] 環境変数 AUDIT_PEPPER（16 文字以上）が必要です。監査ログの参照値を作る鍵です。",
  );
  process.exit(1);
}

const running = await startProtectedServer({
  host: flag("host") ?? process.env["MCP_HTTP_HOST"] ?? "127.0.0.1",
  port: Number(flag("port") ?? process.env["MCP_HTTP_PORT"] ?? "3939"),
  issuer: flag("issuer") ?? process.env["MCP_AS_ISSUER"] ?? "http://127.0.0.1:9100",
  ...(flag("resource") ?? process.env["MCP_RESOURCE"]
    ? { resource: flag("resource") ?? (process.env["MCP_RESOURCE"] as string) }
    : {}),
  auditPepper,
});

console.error(`[${PACKAGE_NAME}] ${running.resource} で待ち受けています（AS: ${running.issuer}）`);

async function shutdown(signal: string): Promise<void> {
  console.error(`[${PACKAGE_NAME}] ${signal} を受け取りました。終了します`);
  await running.close();
  process.exit(0);
}
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
