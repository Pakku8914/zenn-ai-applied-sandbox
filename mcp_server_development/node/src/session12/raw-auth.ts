/**
 * 認証付きの生電文キャプチャ（curl -i の代わり・依存ゼロ）
 *
 *   npx tsx src/session12/raw-auth.ts --preset initialize
 *       → トークンなし。401 と WWW-Authenticate を見る
 *   npx tsx src/session12/raw-auth.ts --method GET --path /.well-known/oauth-protected-resource/mcp
 *       → Protected Resource Metadata を見る
 *   npx tsx src/session12/raw-auth.ts --preset initialize --scope "docs:read"
 *       → 先に OAuth フローを通してトークンを取り、それを付けて叩く
 *   npx tsx src/session12/raw-auth.ts --preset initialize --scope "docs:read" \
 *       --resource https://other.example/mcp
 *       → ❌ 他サービス向けトークンで叩く（10 節の実験）
 *   npx tsx src/session12/raw-auth.ts --preset initialize --token <トークン文字列>
 *
 * クライアント側なので console.log を使ってかまいません。
 */
import { initializeBody, obtainAccessToken, rawRequest } from "./oauth-flow.js";

const PRESETS: Record<string, string> = {
  initialize: initializeBody(),
  "tools-list": JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
  "tools-call": JSON.stringify({
    jsonrpc: "2.0",
    id: 3,
    method: "tools/call",
    params: { name: "search_documents", arguments: { query: "VPN", limit: 2 } },
  }),
  reindex: JSON.stringify({
    jsonrpc: "2.0",
    id: 4,
    method: "tools/call",
    params: { name: "reindex_documents", arguments: {} },
  }),
};

const flags = parseFlags(process.argv.slice(2));
const base = flags.get("url") ?? "http://127.0.0.1:3939/mcp";
const path = flags.get("path");
const url = path === undefined ? base : `${new URL(base).origin}${path}`;
const method = (flags.get("method") ?? (path === undefined ? "POST" : "GET")).toUpperCase();
const preset = flags.get("preset");
const body = preset === undefined ? undefined : PRESETS[preset];
if (preset !== undefined && body === undefined) {
  console.error(`未知のプリセットです: ${preset}（${Object.keys(PRESETS).join(" / ")}）`);
  process.exit(1);
}

let token = flags.get("token");
const scope = flags.get("scope");
if (token === undefined && scope !== undefined) {
  const obtained = await obtainAccessToken({
    mcpUrl: base,
    scope,
    resource: flags.get("resource"),
  });
  for (const step of obtained.steps) {
    console.log(step);
  }
  token = obtained.accessToken;
}

const headers: Record<string, string> = {};
if (body !== undefined) {
  headers["accept"] = "application/json, text/event-stream";
  headers["content-type"] = "application/json";
} else {
  headers["accept"] = "application/json";
}
if (token !== undefined) {
  headers["authorization"] = `Bearer ${token}`;
}

console.log("--- request ---");
console.log(`${method} ${new URL(url).pathname} HTTP/1.1`);
console.log(`host: ${new URL(url).host}`);
for (const [name, value] of Object.entries(headers)) {
  // ★ トークンは全部出さない。ログ・キャプチャ・スクリーンショットからの漏えいを防ぐ
  console.log(`${name}: ${name === "authorization" ? `${value.slice(0, 20)}…（以下省略）` : value}`);
}
if (body !== undefined) {
  console.log("");
  console.log(body);
}

const response = await rawRequest({ method, url, headers, body });
console.log("--- response ---");
console.log(`HTTP/1.1 ${response.status} ${response.statusMessage}`.trimEnd());
for (let index = 0; index < response.rawHeaders.length; index += 2) {
  console.log(`${response.rawHeaders[index] ?? ""}: ${response.rawHeaders[index + 1] ?? ""}`);
}
console.log("--- body ---");
console.log(response.body.trimEnd());

function parseFlags(tokens: readonly string[]): Map<string, string> {
  const result = new Map<string, string>();
  for (let index = 0; index < tokens.length; index += 1) {
    const key = tokens[index];
    if (key === undefined || !key.startsWith("--")) {
      continue;
    }
    const value = tokens[index + 1];
    if (value === undefined || value.startsWith("--")) {
      result.set(key.slice(2), "true");
      continue;
    }
    result.set(key.slice(2), value);
    index += 1;
  }
  return result;
}
