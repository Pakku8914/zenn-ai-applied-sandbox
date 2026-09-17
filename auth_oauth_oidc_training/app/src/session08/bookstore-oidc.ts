// セッション 8 の共通設定。
// 本章は「宛先（aud）が 2 つ出てくる」ことが主題なので、定数の名前で誰宛てかを区別します。

/** コンテナの中のコードが直接叩く URL（ブラウザに渡す URL とは別物。セッション 6 参照） */
export const ISSUER = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

/** RP 自身のクライアント ID。ID トークンの aud はこの値になります */
export const CLIENT_ID = "web-app";
/** リソースサーバー。アクセストークンの aud はこの値になります */
export const API_AUDIENCE = "api-service";

export const JWKS_URI = `${ISSUER}/protocol/openid-connect/certs`;
export const TOKEN_ENDPOINT = `${ISSUER}/protocol/openid-connect/token`;
export const USERINFO_ENDPOINT = `${ISSUER}/protocol/openid-connect/userinfo`;
export const DISCOVERY_URL = `${ISSUER}/.well-known/openid-configuration`;
