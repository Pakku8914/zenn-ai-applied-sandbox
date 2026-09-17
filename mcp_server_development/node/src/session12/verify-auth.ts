/**
 * 認証・認可の検証マトリクス（10 ケース）
 *
 * 前提: 認可サーバー（MCP_AS_DEBUG=on）と保護サーバーが起動していること
 *   docker compose exec node npx tsx src/session12/verify-auth.ts
 *
 * 期待どおりでなければ即座に NG を出し、終了コード 1 で終わります（CI に載せる形）。
 * セッション13 では、この内容を vitest のテストケースに移します。
 */
import { base64UrlEncode, decodeJws } from "./jwt.js";
import { type RawResponse, initializeBody, obtainAccessToken, rawRequest } from "./oauth-flow.js";
import { SCOPE_DOCS_ADMIN, SCOPE_DOCS_READ } from "./scopes.js";

const MCP_URL = process.env["MCP_URL"] ?? "http://127.0.0.1:3939/mcp";
const AS_URL = process.env["MCP_AS_ISSUER"] ?? "http://127.0.0.1:9100";
/** 「他サービス向け」を演じる識別子。実在しなくてよい（aud は文字列の一致でしかない） */
const OTHER_RESOURCE = "https://kintai.example.internal/api";
const TOTAL = 10;

function ok(index: number, label: string, detail: string): void {
  console.log(`[${index}/${TOTAL}] ${label}: ${detail}`);
}

function ng(index: number, label: string, detail: string): never {
  console.log(`[${index}/${TOTAL}] ${label}: ❌ ${detail}`);
  console.log(`NG: ケース${index}（${label}）が期待どおりではありません`);
  process.exit(1);
}

function header(response: RawResponse, name: string): string {
  const value = response.headers[name];
  return (Array.isArray(value) ? value[0] : value) ?? "(なし)";
}

async function post(
  extraHeaders: Record<string, string>,
  body: string = initializeBody(),
): Promise<RawResponse> {
  return rawRequest({
    method: "POST",
    url: MCP_URL,
    headers: {
      accept: "application/json, text/event-stream",
      "content-type": "application/json",
      ...extraHeaders,
    },
    body,
  });
}

/** テスト用トークンの鋳造（MCP_AS_DEBUG=on のときだけ使える口） */
async function mint(params: {
  audience: string;
  scope: string;
  ttlSeconds: number;
}): Promise<string> {
  const response = await rawRequest({
    method: "POST",
    url: `${AS_URL}/debug/mint`,
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(params),
  });
  if (response.status !== 200) {
    throw new Error(
      `テスト用トークンの鋳造に失敗しました（status=${response.status}）。` +
        "認可サーバーを MCP_AS_DEBUG=on で起動していますか",
    );
  }
  const parsed: unknown = JSON.parse(response.body);
  const token = (parsed as { access_token?: unknown }).access_token;
  if (typeof token !== "string") {
    throw new Error("鋳造の応答に access_token がありません");
  }
  return token;
}

/**
 * 署名を壊す。★ 末尾ではなく先頭の 1 文字を変えること。
 * 末尾の文字は「捨てられるビット」を含むので、変えても復号結果が同じになる場合があります。
 */
function tamperSignature(token: string): string {
  const [head, payload, signature] = token.split(".");
  if (head === undefined || payload === undefined || signature === undefined) {
    throw new Error("トークンの形式が不正です");
  }
  const first = signature.slice(0, 1);
  return `${head}.${payload}.${first === "A" ? "B" : "A"}${signature.slice(1)}`;
}

/** alg を none にして署名を空にした偽造トークン（歴史的に多くの実装が破られた形） */
function forgeAlgNone(payload: Record<string, unknown>): string {
  return `${base64UrlEncode(JSON.stringify({ alg: "none", typ: "JWT" }))}.${base64UrlEncode(
    JSON.stringify(payload),
  )}.`;
}

// 正しいトークンを OAuth フローで取得（発見〜PKCE〜交換までを実際に通す）
const valid = await obtainAccessToken({ mcpUrl: MCP_URL, scope: SCOPE_DOCS_READ });

// ------------------------------------------------------- [1] トークンなし
{
  const response = await post({});
  const challenge = header(response, "www-authenticate");
  if (response.status !== 401 || !challenge.includes("resource_metadata=")) {
    ng(1, "トークンなし", `status=${response.status} challenge=${challenge}`);
  }
  ok(1, "トークンなし", `401 / WWW-Authenticate=${challenge}`);
}

// --------------------------------------------------- [2] スキームが Bearer でない
{
  const response = await post({ authorization: "Basic dXNlcjpwYXNzd29yZA==" });
  if (response.status !== 401 || !header(response, "www-authenticate").includes("invalid_request")) {
    ng(2, "スキーム違い", `status=${response.status}`);
  }
  ok(2, "スキーム違い", `401 / error="invalid_request"`);
}

// ------------------------------------------------------- [3] 3 パートでない
{
  const response = await post({ authorization: "Bearer abc.def" });
  if (response.status !== 401 || !header(response, "www-authenticate").includes("invalid_token")) {
    ng(3, "形式不正", `status=${response.status}`);
  }
  ok(3, "形式不正", `401 / error="invalid_token"`);
}

// --------------------------------------------------------- [4] 署名の改ざん
{
  const response = await post({ authorization: `Bearer ${tamperSignature(valid.accessToken)}` });
  if (response.status !== 401) {
    ng(4, "署名の改ざん", `status=${response.status}（通ってしまいました）`);
  }
  ok(4, "署名の改ざん", `401 / error="invalid_token"`);
}

// --------------------------------------------------------- [5] alg=none 偽造
{
  const decoded = decodeJws(valid.accessToken);
  if (decoded === undefined) {
    ng(5, "alg=none 偽造", "正しいトークンを分解できませんでした");
  }
  const response = await post({ authorization: `Bearer ${forgeAlgNone(decoded.payload)}` });
  if (response.status !== 401) {
    ng(5, "alg=none 偽造", `status=${response.status}（署名なしで通ってしまいました）`);
  }
  ok(5, "alg=none 偽造", `401 / error="invalid_token"（許可リストに RS256 だけを載せている効果）`);
}

// ------------------------------------------------------------- [6] 期限切れ
{
  const expired = await mint({ audience: MCP_URL, scope: SCOPE_DOCS_READ, ttlSeconds: -600 });
  const response = await post({ authorization: `Bearer ${expired}` });
  if (response.status !== 401) {
    ng(6, "期限切れ", `status=${response.status}`);
  }
  ok(6, "期限切れ", `401 / error="invalid_token"`);
}

// ------------------------------------------------- [7] 他サービス向け（aud 不一致）
{
  const other = await mint({ audience: OTHER_RESOURCE, scope: SCOPE_DOCS_READ, ttlSeconds: 300 });
  const response = await post({ authorization: `Bearer ${other}` });
  if (response.status !== 401) {
    ng(
      7,
      "他サービス向け（aud 不一致）",
      `status=${response.status}（MCP_AUTH_SKIP_AUD=on で起動していませんか）`,
    );
  }
  ok(7, "他サービス向け（aud 不一致）", `401 / error="invalid_token"`);
}

// ----------------------------------------------------- [8] ベーススコープ不足
{
  const adminOnly = await mint({ audience: MCP_URL, scope: SCOPE_DOCS_ADMIN, ttlSeconds: 300 });
  const response = await post({ authorization: `Bearer ${adminOnly}` });
  const challenge = header(response, "www-authenticate");
  if (response.status !== 403 || !challenge.includes("insufficient_scope")) {
    ng(8, "ベーススコープ不足", `status=${response.status} challenge=${challenge}`);
  }
  ok(8, "ベーススコープ不足", `403 / ${challenge}`);
}

// --------------------------------------------------------- [9] 正しいトークン
let sessionId = "";
{
  const response = await post({ authorization: `Bearer ${valid.accessToken}` });
  sessionId = header(response, "mcp-session-id");
  if (response.status !== 200 || sessionId === "(なし)") {
    ng(9, "正しいトークン", `status=${response.status} session=${sessionId}`);
  }
  ok(9, "正しいトークン", `200 / content-type=${header(response, "content-type")}`);
}

// ------------------------------------------------------- [10] tools/list まで
{
  const response = await post(
    {
      authorization: `Bearer ${valid.accessToken}`,
      "mcp-session-id": sessionId,
      "mcp-protocol-version": "2025-11-25",
    },
    JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
  );
  if (response.status !== 200 || !response.body.includes("search_documents")) {
    ng(10, "tools/list", `status=${response.status} body=${response.body.slice(0, 120)}`);
  }
  const hasAdmin = response.body.includes("reindex_documents");
  ok(10, "tools/list", `200 / search_documents あり / reindex_documents=${hasAdmin ? "あり" : "なし"}`);
}

// 後片付け。セッションを残さない
await rawRequest({
  method: "DELETE",
  url: MCP_URL,
  headers: {
    authorization: `Bearer ${valid.accessToken}`,
    "mcp-session-id": sessionId,
    "mcp-protocol-version": "2025-11-25",
  },
});

console.log(`OK: ${TOTAL}/${TOTAL}`);
