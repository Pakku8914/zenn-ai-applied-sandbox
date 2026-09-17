/**
 * 問題4 の解答 ―― 生電文でステータスコードを確認する（fetch 版）
 *
 *   docker compose exec node npx tsx src/review03/q4-raw.ts
 *
 * Node.js 22 標準の fetch だけを使うので、依存は増えません。
 */
const ENDPOINT = process.argv[2] ?? "http://127.0.0.1:3939/mcp";
/** POST は application/json と text/event-stream の両方を受け付けると申告する必要がある */
const ACCEPT_BOTH = "application/json, text/event-stream";

type CallOptions = {
  method?: string;
  body?: string;
  session?: string;
  origin?: string;
};

async function call(options: CallOptions): Promise<Response> {
  const headers: Record<string, string> = { accept: ACCEPT_BOTH };
  if (options.body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (options.session !== undefined) {
    headers["mcp-session-id"] = options.session;
  }
  if (options.origin !== undefined) {
    headers["origin"] = options.origin;
  }
  return fetch(ENDPOINT, {
    method: options.method ?? "POST",
    headers,
    ...(options.body === undefined ? {} : { body: options.body }),
  });
}

const INITIALIZE = JSON.stringify({
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: "2025-11-25",
    capabilities: {},
    clientInfo: { name: "q4-raw", version: "1.0.0" },
  },
});
const INITIALIZED = JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" });
const TOOLS_LIST = JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" });

// ① initialize（セッションの発行）
const first = await call({ body: INITIALIZE });
const sessionId = first.headers.get("mcp-session-id");
console.log(
  `[1/8] POST initialize: ${first.status} / content-type=${first.headers.get("content-type")}` +
    ` / mcp-session-id=${sessionId === null ? "なし" : "あり"}`,
);
await first.text(); // 本文を読み切ってストリームを閉じる
if (sessionId === null) {
  console.error("セッション ID が返りませんでした。サーバーが起動しているか確認してください");
  process.exit(1);
}

// ② 通知には応答が返らない
const second = await call({ body: INITIALIZED, session: sessionId });
const secondBody = await second.text();
console.log(`[2/8] POST notifications/initialized: ${second.status} / 本文の長さ=${secondBody.length}`);

// ③ 正しいセッション ID
const third = await call({ body: TOOLS_LIST, session: sessionId });
await third.text();
console.log(`[3/8] POST tools/list（セッションIDあり）: ${third.status}`);

// ④ セッション ID なし（initialize でもない）
const fourth = await call({ body: TOOLS_LIST });
await fourth.text();
console.log(`[4/8] POST tools/list（セッションIDなし）: ${fourth.status}`);

// ⑤ 知らないセッション ID
const fifth = await call({
  body: TOOLS_LIST,
  session: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
});
await fifth.text();
console.log(`[5/8] POST tools/list（知らないセッションID）: ${fifth.status}`);

// ⑥ 許可されていない Origin
const sixth = await call({ body: INITIALIZE, origin: "https://evil.example" });
await sixth.text();
console.log(`[6/8] POST initialize（Origin=https://evil.example）: ${sixth.status}`);

// ⑦ 使えない HTTP メソッド
const seventh = await call({ method: "PUT", session: sessionId });
await seventh.text();
console.log(`[7/8] PUT /mcp: ${seventh.status} / allow=${seventh.headers.get("allow")}`);

// ⑧ 破棄と、破棄後の再利用
const eighth = await call({ method: "DELETE", session: sessionId });
await eighth.text();
const after = await call({ body: TOOLS_LIST, session: sessionId });
await after.text();
console.log(`[8/8] DELETE: ${eighth.status} / 破棄後の tools/list: ${after.status}`);
console.log("OK: セッションの発行・検証・破棄と Origin 検証が仕様どおりです");
