// セッション 6 の共通設定。
// 同じ認可サーバーでも「ブラウザから見た名前」と「コンテナから見た名前」が違うので、
// 2 つの URL を別の定数として持ちます。混ぜると必ず動かなくなります。

/** ブラウザに渡す URL。ホストのポートマッピング（127.0.0.1:8080）に届く */
export const ISSUER_PUBLIC = process.env["ISSUER_PUBLIC"] ?? "http://localhost:8080/realms/bookstore";
/** コンテナの中のコードが直接叩く URL。compose のサービス名で解決する */
export const ISSUER_INTERNAL = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

export const REALM = "bookstore";
export const CLIENT_ID = "web-app";
/** realm に登録した値と 1 文字も違ってはいけません（完全一致で照合されます） */
export const REDIRECT_URI = "http://localhost:3100/callback";
export const SCOPE = "openid profile email";

/** realm を含まない Keycloak 本体の URL（Admin REST API で使う） */
export const KEYCLOAK_BASE_INTERNAL = ISSUER_INTERNAL.replace(/\/realms\/[^/]+$/, "");

export const authorizationEndpoint = (issuer: string): string => `${issuer}/protocol/openid-connect/auth`;
export const tokenEndpoint = (issuer: string): string => `${issuer}/protocol/openid-connect/token`;
