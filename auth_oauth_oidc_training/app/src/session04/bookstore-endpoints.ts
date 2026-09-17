// セッション 4 の共通モジュール。トークンと公開鍵の入手口をまとめてあります。

// コンテナの中から認可サーバーを呼ぶので ISSUER_INTERNAL を使います
export const ISSUER = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";
// リソースサーバー（api-service）が「自分宛てのトークンか」を確かめるときの宛先
export const AUDIENCE = "api-service";
// どちらも環境構築の章で discovery から確認した URL と同じ値です
export const TOKEN_ENDPOINT = `${ISSUER}/protocol/openid-connect/token`;
export const JWKS_URI = `${ISSUER}/protocol/openid-connect/certs`;

/**
 * batch-worker（機密クライアント）としてアクセストークンを 1 本もらいます。
 * 「どうやって取るか」はセッション 5 以降のテーマなので、本章では立ち入りません。
 */
export async function fetchAccessToken(): Promise<string> {
  const res = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: "batch-worker",
      // 学習用サンドボックスの固定値。本番では環境変数や Secret Manager から読みます
      client_secret: "batch-worker-secret",
    }),
  });
  if (!res.ok) {
    throw new Error(`トークンの取得に失敗しました: HTTP ${res.status}`);
  }
  const body = (await res.json()) as { access_token?: string };
  if (body.access_token === undefined) {
    throw new Error("レスポンスに access_token が含まれていません");
  }
  return body.access_token;
}

/** JWKS から、いま署名に使われている RS256 の公開鍵を 1 つ取り出します */
export async function fetchSigningKey(): Promise<{ kid: string; modulus: string }> {
  const res = await fetch(JWKS_URI);
  if (!res.ok) {
    throw new Error(`JWKS の取得に失敗しました: HTTP ${res.status}`);
  }
  const jwks = (await res.json()) as {
    keys?: Array<{ kid?: string; use?: string; alg?: string; n?: string }>;
  };
  const key = (jwks.keys ?? []).find((k) => k.use === "sig" && k.alg === "RS256");
  if (key === undefined || key.kid === undefined || key.n === undefined) {
    throw new Error("JWKS に RS256 の署名鍵が見つかりません");
  }
  // modulus は公開鍵の本体。JWKS は公開情報なので、誰でもこの文字列を読めます
  return { kid: key.kid, modulus: key.n };
}
