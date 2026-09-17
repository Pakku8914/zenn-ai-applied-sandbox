/**
 * HTTP ＋ OAuth 2.1 の受け入れ条件 1〜14 を確認する（依存ゼロ・fetch のみ）
 *
 *   docker compose exec node npx tsx src/final/verify-http.ts
 *
 * 事前に認可サーバーと MCP サーバーを背面起動しておくこと。
 */
import { mintToken } from "./mint.js";

const ORIGIN = "http://127.0.0.1:3939";
const MCP_URL = `${ORIGIN}/mcp`;
const METADATA_URL = `${ORIGIN}/.well-known/oauth-protected-resource/mcp`;

let passed = 0;
let failed = 0;

function check(no: number, label: string, ok: boolean, detail = ""): void {
  if (ok) passed += 1;
  else failed += 1;
  console.log(`[${String(no).padStart(2, " ")}] ${ok ? "OK  " : "NG  "}${label}${detail === "" ? "" : ` — ${detail}`}`);
}

/** Streamable HTTP の応答は SSE のことも JSON のこともある */
async function readMcp(response: Response): Promise<Record<string, unknown> | undefined> {
  const text = await response.text();
  const contentType = response.headers.get("content-type") ?? "";
  const raw = contentType.includes("text/event-stream")
    ? text.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim()
    : text.trim();
  if (raw === undefined || raw === "") return undefined;
  return JSON.parse(raw) as Record<string, unknown>;
}

function post(body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return fetch(MCP_URL, {
    method: "POST",
    headers: {
      accept: "application/json, text/event-stream",
      "content-type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

const initialize = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: "2025-11-25",
    capabilities: {},
    clientInfo: { name: "final-verify", version: "1.0.0" },
  },
};

// 1. メタデータ
const metadata = await fetch(METADATA_URL, { headers: { accept: "application/json" } });
const metadataBody = (await metadata.json()) as {
  resource?: string;
  scopes_supported?: string[];
  resource_name?: string;
};
check(1, "メタデータが 200 で返る", metadata.status === 200);
check(
  15,
  "メタデータが requests:* を告知している",
  JSON.stringify(metadataBody.scopes_supported) ===
    JSON.stringify(["requests:read", "requests:write", "requests:approve"]),
  `resource=${metadataBody.resource} name=${metadataBody.resource_name}`,
);

// 2. トークン無し
const noToken = await post(initialize);
const challenge = noToken.headers.get("www-authenticate") ?? "";
check(2, "トークン無しで 401", noToken.status === 401);
check(2, "WWW-Authenticate に resource_metadata", challenge.includes("resource_metadata="));

// 3. aud が別サービス
const otherAud = await mintToken({ audience: "https://other.example/mcp", scope: "requests:read" });
check(
  3,
  "別サービス向けトークンで 401",
  (await post(initialize, { authorization: `Bearer ${otherAud}` })).status === 401,
);

// 4. 期限切れ
const expired = await mintToken({ audience: MCP_URL, scope: "requests:read", ttlSeconds: -600 });
check(
  4,
  "期限切れトークンで 401",
  (await post(initialize, { authorization: `Bearer ${expired}` })).status === 401,
);

// 5. 署名の改ざん
const valid = await mintToken({ audience: MCP_URL, scope: "requests:read requests:approve" });
const tampered = `${valid.slice(0, -1)}${valid.endsWith("A") ? "B" : "A"}`;
check(
  5,
  "署名を書き換えたトークンで 401",
  (await post(initialize, { authorization: `Bearer ${tampered}` })).status === 401,
);

// 6. ベーススコープ不足
const writeOnly = await mintToken({ audience: MCP_URL, scope: "requests:write" });
const insufficient = await post(initialize, { authorization: `Bearer ${writeOnly}` });
check(
  6,
  "requests:read が無いと 403 insufficient_scope",
  insufficient.status === 403 &&
    (insufficient.headers.get("www-authenticate") ?? "").includes("insufficient_scope"),
);

// 7. 正常な initialize
const readToken = await mintToken({ audience: MCP_URL, scope: "requests:read" });
const initialized = await post(initialize, { authorization: `Bearer ${readToken}` });
const sessionId = initialized.headers.get("mcp-session-id") ?? "";
await readMcp(initialized);
check(7, "正常なトークンで 200 とセッション ID", initialized.status === 200 && sessionId !== "");
await post({ jsonrpc: "2.0", method: "notifications/initialized" }, {
  authorization: `Bearer ${readToken}`,
  "mcp-session-id": sessionId,
});

// 8. tools/list
const listed = await post({ jsonrpc: "2.0", id: 2, method: "tools/list" }, {
  authorization: `Bearer ${readToken}`,
  "mcp-session-id": sessionId,
});
const listBody = await readMcp(listed);
const tools = ((listBody?.["result"] as { tools?: unknown[] } | undefined)?.tools ?? []).length;
check(8, "tools/list が 6 本", listed.status === 200 && tools === 6, `tools=${tools}`);

// 9. read だけで decide_request
const denied = await post(
  {
    jsonrpc: "2.0",
    id: 3,
    method: "tools/call",
    params: { name: "decide_request", arguments: { requestId: "req-1002", decision: "approve" } },
  },
  { authorization: `Bearer ${readToken}`, "mcp-session-id": sessionId },
);
const deniedBody = await readMcp(denied);
const deniedResult = deniedBody?.["result"] as
  | { isError?: boolean; content?: Array<{ text?: string }> }
  | undefined;
check(
  9,
  "read だけの decide は HTTP 200 ＋ isError ＋ forbidden",
  denied.status === 200 &&
    deniedResult?.isError === true &&
    (deniedResult.content?.[0]?.text ?? "").includes("[forbidden]"),
);

// 10. approve 付きのトークンで新しいセッションを張る
const approveInit = await post(initialize, { authorization: `Bearer ${valid}` });
const approveSession = approveInit.headers.get("mcp-session-id") ?? "";
await readMcp(approveInit);
await post({ jsonrpc: "2.0", method: "notifications/initialized" }, {
  authorization: `Bearer ${valid}`,
  "mcp-session-id": approveSession,
});
const dry = await post(
  {
    jsonrpc: "2.0",
    id: 4,
    method: "tools/call",
    params: { name: "decide_request", arguments: { requestId: "req-1002", decision: "approve" } },
  },
  { authorization: `Bearer ${valid}`, "mcp-session-id": approveSession },
);
const dryResult = (await readMcp(dry))?.["result"] as
  | { isError?: boolean; structuredContent?: { applied?: boolean } }
  | undefined;
check(
  10,
  "approve 付きならドライランが通る",
  dryResult?.isError !== true && dryResult?.structuredContent?.applied === false,
);

// 11. Origin
const evil = await post(initialize, {
  authorization: `Bearer ${readToken}`,
  origin: "https://evil.example",
});
check(11, "許可外の Origin で 403", evil.status === 403);

// 12. セッション ID 無し
const noSession = await post({ jsonrpc: "2.0", id: 5, method: "tools/list" }, {
  authorization: `Bearer ${readToken}`,
});
check(12, "セッション ID 無しの tools/list で 400", noSession.status === 400);

// 13. 未知のセッション ID
const unknownSession = await post({ jsonrpc: "2.0", id: 6, method: "tools/list" }, {
  authorization: `Bearer ${readToken}`,
  "mcp-session-id": "00000000-0000-4000-8000-000000000000",
});
check(13, "未知のセッション ID で 404", unknownSession.status === 404);

// 14. DELETE
const deleted = await fetch(MCP_URL, {
  method: "DELETE",
  headers: { authorization: `Bearer ${readToken}`, "mcp-session-id": sessionId },
});
const afterDelete = await post({ jsonrpc: "2.0", id: 7, method: "tools/list" }, {
  authorization: `Bearer ${readToken}`,
  "mcp-session-id": sessionId,
});
check(14, "DELETE でセッションが破棄される", deleted.status < 300 && afterDelete.status === 404);

console.log(`\n合格 ${passed} 件 / 不合格 ${failed} 件`);
if (failed > 0) process.exit(1);
