// 利用者が関わらないフロー（Client Credentials）では何が返るのかを確かめます。
// リフレッシュトークンが返らないことの実証に使います。
import { BATCH_CLIENT_ID, BATCH_CLIENT_SECRET, tokenEndpoint } from "./bookstore-tokens.js";

export async function inspectClientCredentials(): Promise<{
  keys: string[];
  hasRefreshToken: boolean;
  expiresIn: number;
  scope: string;
}> {
  const res = await fetch(tokenEndpoint(), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: BATCH_CLIENT_ID,
      client_secret: BATCH_CLIENT_SECRET,
    }),
  });
  const body = (await res.json()) as Record<string, unknown>;
  if (!res.ok) {
    throw new Error(`Client Credentials が HTTP ${res.status} で失敗しました: ${JSON.stringify(body)}`);
  }
  return {
    keys: Object.keys(body).sort(),
    hasRefreshToken: "refresh_token" in body,
    expiresIn: typeof body["expires_in"] === "number" ? body["expires_in"] : -1,
    scope: typeof body["scope"] === "string" ? body["scope"] : "",
  };
}
