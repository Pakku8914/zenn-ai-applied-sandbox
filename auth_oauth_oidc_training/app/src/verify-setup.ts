// サンドボックス全体の自己検証スクリプト。
// 期待値と一致しない場合は非 0 で終了するため、人が出力を読んで判断する必要はありません。
import { createRemoteJWKSet, jwtVerify } from "jose";

const issuer = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

// 1. discovery が引けること（認可サーバーが起動し、realm が import されている）
const discoveryRes = await fetch(`${issuer}/.well-known/openid-configuration`);
check("discovery の HTTP ステータス", discoveryRes.status, 200);
const discovery = (await discoveryRes.json()) as {
  issuer: string;
  token_endpoint: string;
  code_challenge_methods_supported?: string[];
};
check("issuer", discovery.issuer, issuer);
check(
  "PKCE で S256 が使えるか",
  (discovery.code_challenge_methods_supported ?? []).includes("S256"),
  true,
);

// 2. Client Credentials フローでアクセストークンが取れること（機密クライアント）
const tokenRes = await fetch(discovery.token_endpoint, {
  method: "POST",
  headers: { "content-type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({
    grant_type: "client_credentials",
    client_id: "batch-worker",
    client_secret: "batch-worker-secret",
  }),
});
check("トークンエンドポイントの HTTP ステータス", tokenRes.status, 200);
const token = (await tokenRes.json()) as { access_token: string; token_type: string };
check("token_type", token.token_type.toLowerCase(), "bearer");

// 3. 受け取ったアクセストークンを JWKS で検証できること（リソースサーバー側の処理）
const jwks = createRemoteJWKSet(new URL(`${issuer}/protocol/openid-connect/certs`));
const { payload, protectedHeader } = await jwtVerify(token.access_token, jwks, {
  issuer,
  audience: "api-service",
});
check("署名アルゴリズム", protectedHeader.alg, "RS256");
check("azp（トークンを要求したクライアント）", payload["azp"], "batch-worker");
const audiences = typeof payload.aud === "string" ? [payload.aud] : (payload.aud ?? []);
check("aud（トークンの宛先）に api-service が含まれるか", audiences.includes("api-service"), true);

// 4. 公開クライアントがクライアント認証情報フローを使えないこと（設定ミスの検出）
const forbidden = await fetch(discovery.token_endpoint, {
  method: "POST",
  headers: { "content-type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({ grant_type: "client_credentials", client_id: "web-app" }),
});
check("公開クライアントの client_credentials が拒否されるか", forbidden.status, 401);

console.log(failures === 0 ? "\nすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`);
process.exit(failures === 0 ? 0 : 1);
