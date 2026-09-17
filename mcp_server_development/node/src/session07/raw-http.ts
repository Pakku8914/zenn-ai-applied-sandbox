/**
 * 生電文キャプチャ用の最小 HTTP クライアント（curl -i の代わり）
 *
 * node:http だけで書いてあるので、コンテナに curl が入っていなくても
 * ヘッダー込みの生の応答を確認できます。
 *
 * 使い方:
 *   npx tsx src/session07/raw-http.ts POST   --preset initialize
 *   npx tsx src/session07/raw-http.ts POST   --preset initialized --session <id>
 *   npx tsx src/session07/raw-http.ts POST   --preset tools-list  --session <id>
 *   npx tsx src/session07/raw-http.ts POST   --preset tools-call  --session <id>
 *   npx tsx src/session07/raw-http.ts GET    --session <id> --seconds 3
 *   npx tsx src/session07/raw-http.ts DELETE --session <id>
 *
 * 主なオプション
 *   --accept both|json|sse|none   Accept ヘッダー（既定: POST=both / GET=sse）
 *   --origin <値>                 Origin ヘッダーを付ける
 *   --session <id>                Mcp-Session-Id ヘッダー
 *   --last-event-id <id>          Last-Event-ID ヘッダー（再開の実験）
 *   --protocol <版>|off           MCP-Protocol-Version ヘッダー（既定 2025-11-25）
 *   --body <JSON>                 プリセットを使わず本文を直接指定
 *   --host / --port / --path      接続先（既定 127.0.0.1 / 3939 / /mcp）
 *   --seconds <N>                 N 秒で打ち切る（既定: GET=3 / それ以外=10）
 *
 * これはクライアント側のスクリプトなので console.log を使ってかまいません
 * （禁止されるのは「stdio サーバープロセスの stdout」だけです）。
 */
import http from "node:http";

const PRESETS: Record<string, string> = {
  initialize: JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-11-25",
      capabilities: {},
      clientInfo: { name: "raw-http", version: "1.0.0" },
    },
  }),
  initialized: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
  "tools-list": JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
  "tools-call": JSON.stringify({
    jsonrpc: "2.0",
    id: 3,
    method: "tools/call",
    params: { name: "search_documents", arguments: { query: "VPN", limit: 2 } },
  }),
  // 壊れた JSON（400 の再現用）
  broken: '{"jsonrpc":"2.0","id":9,',
};

const ACCEPTS: Record<string, string> = {
  both: "application/json, text/event-stream",
  json: "application/json",
  sse: "text/event-stream",
};

const argv = process.argv.slice(2);
const method = (argv[0] ?? "POST").toUpperCase();
const flags = parseFlags(argv.slice(1));

const host = flags.get("host") ?? "127.0.0.1";
const port = Number(flags.get("port") ?? "3939");
const path = flags.get("path") ?? "/mcp";
const seconds = Number(flags.get("seconds") ?? (method === "GET" ? "3" : "10"));

const preset = flags.get("preset");
const body = flags.get("body") ?? (preset === undefined ? undefined : PRESETS[preset]);
if (preset !== undefined && body === undefined) {
  console.error(`未知のプリセットです: ${preset}（使えるのは ${Object.keys(PRESETS).join(" / ")}）`);
  process.exit(1);
}

const headers: Record<string, string> = { host: `${host}:${port}` };

const acceptKey = flags.get("accept") ?? (method === "GET" ? "sse" : "both");
if (acceptKey !== "none") {
  const accept = ACCEPTS[acceptKey];
  if (accept === undefined) {
    console.error(`未知の accept です: ${acceptKey}（both / json / sse / none）`);
    process.exit(1);
  }
  headers["accept"] = accept;
}

if (body !== undefined) {
  headers["content-type"] = "application/json";
  headers["content-length"] = String(Buffer.byteLength(body, "utf8"));
}

const session = flags.get("session");
if (session !== undefined) {
  headers["mcp-session-id"] = session;
}
const lastEventId = flags.get("last-event-id");
if (lastEventId !== undefined) {
  headers["last-event-id"] = lastEventId;
}
const origin = flags.get("origin");
if (origin !== undefined) {
  headers["origin"] = origin;
}
// initialize 以外には合意済みのプロトコル版を申告するのが仕様の要求
const protocol = flags.get("protocol") ?? "2025-11-25";
if (preset !== "initialize" && protocol !== "off") {
  headers["mcp-protocol-version"] = protocol;
}

console.log("--- request ---");
console.log(`${method} ${path} HTTP/1.1`);
for (const [name, value] of Object.entries(headers)) {
  console.log(`${name}: ${value}`);
}
if (body !== undefined) {
  console.log("");
  console.log(body);
}

const request = http.request({ host, port, path, method, headers }, (response) => {
  console.log("--- response ---");
  console.log(`HTTP/${response.httpVersion} ${response.statusCode ?? 0} ${response.statusMessage ?? ""}`.trimEnd());
  // rawHeaders は [名前, 値, 名前, 値, ...] の並び。実際の大文字小文字がそのまま見える
  const raw = response.rawHeaders;
  for (let index = 0; index < raw.length; index += 2) {
    console.log(`${raw[index] ?? ""}: ${raw[index + 1] ?? ""}`);
  }
  console.log("--- body ---");
  response.setEncoding("utf8");
  response.on("data", (chunk: string) => process.stdout.write(chunk));
  response.on("end", () => {
    clearTimeout(timer);
    console.log("--- end（サーバーが閉じました） ---");
  });
});

request.on("error", (error: Error) => {
  console.error(`リクエストに失敗しました: ${error.message}`);
  process.exit(1);
});

const timer = setTimeout(() => {
  console.log(`--- end（${seconds} 秒経過したのでクライアントから切断しました） ---`);
  request.destroy();
}, seconds * 1000);

if (body !== undefined) {
  request.write(body);
}
request.end();

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
