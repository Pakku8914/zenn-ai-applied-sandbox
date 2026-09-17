// セッション 7 の共通設定。
// トークンの寿命はすべて realm 定義（keycloak/import/realm-bookstore.json）に書かれた値です。
// コードに数値を書き写すのは「章の説明用」で、本来の正は realm 側にあります。

/** コンテナの中のコードが直接叩く URL。compose のサービス名で解決する */
export const ISSUER_INTERNAL = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";
export const REALM = "bookstore";
export const CLIENT_ID = "web-app";
export const BATCH_CLIENT_ID = "batch-worker";
/** サンドボックス専用の固定値。本番では環境変数や Secret Manager から読みます */
export const BATCH_CLIENT_SECRET = "batch-worker-secret";

/** realm を含まない Keycloak 本体の URL（Admin REST API で使う） */
export const KEYCLOAK_BASE_INTERNAL = ISSUER_INTERNAL.replace(/\/realms\/[^/]+$/, "");

export const tokenEndpoint = (issuer: string = ISSUER_INTERNAL): string =>
  `${issuer}/protocol/openid-connect/token`;

/** realm の accessTokenLifespan（秒）。アクセストークンの有効期間 */
export const ACCESS_TOKEN_LIFESPAN = 300;
/** realm の ssoSessionIdleTimeout（秒）。リフレッシュトークンの有効期間はこれに揃う */
export const REFRESH_IDLE_TIMEOUT = 1800;
