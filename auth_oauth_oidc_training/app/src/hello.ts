// 認可サーバー（Keycloak）が公開している OpenID Connect の設定情報を取得して表示します。
// このファイルはサンドボックスが正しく動いているかを確かめるための最小サンプルです。
const issuer = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

type Discovery = {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  jwks_uri: string;
  code_challenge_methods_supported?: string[];
};

const res = await fetch(`${issuer}/.well-known/openid-configuration`);
if (!res.ok) {
  throw new Error(`discovery の取得に失敗しました: HTTP ${res.status}`);
}
const doc = (await res.json()) as Discovery;

console.log("こんにちは、認証・認可の実践入門へ！");
console.log(`issuer                 : ${doc.issuer}`);
console.log(`authorization_endpoint : ${doc.authorization_endpoint}`);
console.log(`token_endpoint         : ${doc.token_endpoint}`);
console.log(`jwks_uri               : ${doc.jwks_uri}`);
console.log(`PKCE の方式            : ${(doc.code_challenge_methods_supported ?? []).join(", ")}`);
