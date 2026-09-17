// セッション 2: 認可サーバーが実在することを、自己紹介（discovery）を取得して確かめます。
// 実行: docker compose exec app npx tsx src/session02/client-discovery.ts
const issuer = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

/** discovery ドキュメントは項目が多いので、この章で見るものだけを型にしておきます。 */
type Discovery = {
  issuer: string;
  authorization_endpoint?: string;
  token_endpoint?: string;
  userinfo_endpoint?: string;
  jwks_uri?: string;
  introspection_endpoint?: string;
  revocation_endpoint?: string;
  end_session_endpoint?: string;
};

/** 見るエンドポイントと、それが認証・認可のどちらの仕事に関わるかの対応。 */
const endpoints: readonly { key: keyof Discovery; side: string; note: string }[] = [
  { key: "authorization_endpoint", side: "認証", note: "利用者本人に「誰であるか」を確かめさせる入口" },
  { key: "token_endpoint", side: "認可", note: "確かめた結果をトークン（許可の証）に換える" },
  { key: "userinfo_endpoint", side: "認証", note: "認証済みの利用者の属性を返す" },
  { key: "jwks_uri", side: "検証", note: "トークンの署名を確かめる公開鍵を配る" },
  { key: "introspection_endpoint", side: "検証", note: "そのトークンがまだ有効かを問い合わせる" },
  { key: "revocation_endpoint", side: "運用", note: "発行済みのトークンを無効にする" },
  { key: "end_session_endpoint", side: "認証", note: "認可サーバー側のログイン状態を終わらせる" },
];

const res = await fetch(`${issuer}/.well-known/openid-configuration`);
if (!res.ok) {
  throw new Error(`discovery の取得に失敗しました: HTTP ${res.status}`);
}
const doc = (await res.json()) as Discovery;

console.log("=== 認可サーバーの自己紹介（discovery）を読む ===");
console.log(`issuer: ${doc.issuer}`);
console.log("");
for (const endpoint of endpoints) {
  // 値そのものは長い URL なので、ここでは「あるかないか」だけを見ます
  const exists = doc[endpoint.key] === undefined ? "なし" : "あり";
  console.log(`[${endpoint.side}] ${endpoint.key}: ${exists} — ${endpoint.note}`);
}
console.log("\nこのうち「誰であるか」を確かめるのが認証、「何を許すか」を証にするのが認可です。");
