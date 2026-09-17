// イントロスペクション（RFC 7662）で認可サーバーに問い合わせる側のコード。
// ローカル検証（署名と時刻をこちらで確かめる）との違いを比べるために使います。
import { ISSUER } from "../session04/bookstore-endpoints.js";
import { verifyAccessToken } from "../session04/api-service-verify-jwt.js";

export const INTROSPECTION_ENDPOINT = `${ISSUER}/protocol/openid-connect/token/introspect`;

/** 問い合わせる側（リソースサーバー）は、自分のクライアント資格情報で認証します */
export const API_CLIENT_ID = "api-service";
/** 学習用サンドボックスの固定値。本番では環境変数や Secret Manager から読みます */
export const API_CLIENT_SECRET = "api-service-secret";

export interface IntrospectionResponse {
  /** これが false なら「今この瞬間は使えない」。唯一必須のフィールド（RFC 7662 §2.2） */
  active: boolean;
  sub?: string;
  aud?: string | string[];
  azp?: string;
  scope?: string;
  exp?: number;
  client_id?: string;
  username?: string;
  token_type?: string;
  [claim: string]: unknown;
}

/** アクセストークンを認可サーバーに問い合わせます（Basic 認証で自分を名乗る） */
export async function introspect(token: string): Promise<IntrospectionResponse> {
  const basic = Buffer.from(`${API_CLIENT_ID}:${API_CLIENT_SECRET}`).toString("base64");
  const res = await fetch(INTROSPECTION_ENDPOINT, {
    method: "POST",
    headers: {
      authorization: `Basic ${basic}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ token }),
  });
  if (!res.ok) {
    // 401 が返るのは「問い合わせる側の資格情報」が違うとき。トークンの状態とは無関係です
    throw new Error(`イントロスペクションが HTTP ${res.status} を返しました`);
  }
  return (await res.json()) as IntrospectionResponse;
}

export type Comparison = {
  /** 手元の鍵と時計だけで判断した結果 */
  local: "ok" | "rejected";
  /** 認可サーバーに聞いた結果 */
  remoteActive: boolean;
};

/** 同じトークンを 2 つの方法で確かめ、結果が食い違うかどうかを見ます */
export async function compareLocalAndRemote(token: string): Promise<Comparison> {
  let local: "ok" | "rejected" = "ok";
  try {
    await verifyAccessToken(token);
  } catch {
    local = "rejected";
  }
  const { active } = await introspect(token);
  return { local, remoteActive: active };
}
