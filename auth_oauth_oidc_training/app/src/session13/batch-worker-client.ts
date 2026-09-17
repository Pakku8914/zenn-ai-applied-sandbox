// セッション 13: 利用者が関わらないフロー（Client Credentials）でトークンを取ります。
// クライアント認証の方式を切り替えられるようにして、
// client_secret_basic と client_secret_post の違いが「秘密の置き場所だけ」であることを確かめます。
import { TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";

/** 夜間バッチの機密クライアント。secret は学習用サンドボックスの固定値です */
export const BATCH_CLIENT_ID = "batch-worker";
export const BATCH_CLIENT_SECRET = "batch-worker-secret";

/** サンドボックスで実際に試せる 2 方式。残りの 2 方式は本文の第 2 節で扱います */
export type ClientAuthMethod = "client_secret_basic" | "client_secret_post";

export type TokenRequest = {
  readonly headers: Record<string, string>;
  readonly body: URLSearchParams;
};

/**
 * RFC 6749 §2.3.1 の Basic 認証。
 * client_id と client_secret を URL エンコードしてから連結し、Base64 にします。
 */
export function basicCredentials(clientId: string, clientSecret: string): string {
  const pair = `${encodeURIComponent(clientId)}:${encodeURIComponent(clientSecret)}`;
  return `Basic ${Buffer.from(pair).toString("base64")}`;
}

export type TokenRequestOptions = {
  /** 既定は client_secret_basic（秘密を Authorization ヘッダに置く） */
  readonly method?: ClientAuthMethod;
  readonly scope?: string;
  /** DPoP の証明。付けるとトークンが鍵に縛られます（後半で扱います） */
  readonly dpopProof?: string;
};

/** 方式ごとに「秘密をどこに置くか」だけを差し替えたリクエストを組み立てます */
export function buildTokenRequest(options: TokenRequestOptions = {}): TokenRequest {
  const { method = "client_secret_basic", scope, dpopProof } = options;
  const headers: Record<string, string> = { "content-type": "application/x-www-form-urlencoded" };
  const body = new URLSearchParams({ grant_type: "client_credentials", client_id: BATCH_CLIENT_ID });

  if (method === "client_secret_basic") {
    headers["authorization"] = basicCredentials(BATCH_CLIENT_ID, BATCH_CLIENT_SECRET);
  } else {
    body.set("client_secret", BATCH_CLIENT_SECRET);
  }
  if (scope !== undefined) body.set("scope", scope);
  // DPoP ヘッダは「このリクエストのための証明」です。使い回せません
  if (dpopProof !== undefined) headers["dpop"] = dpopProof;

  return { headers, body };
}

export type TokenResult = {
  readonly status: number;
  readonly keys: readonly string[];
  readonly tokenType: string;
  readonly hasRefreshToken: boolean;
  readonly expiresIn: number;
  readonly scope: string;
  readonly accessToken: string;
};

/** トークンエンドポイントを 1 回叩き、結果を比べやすい形に直します */
export async function requestClientCredentials(options: TokenRequestOptions = {}): Promise<TokenResult> {
  const { headers, body } = buildTokenRequest(options);
  const res = await fetch(TOKEN_ENDPOINT, { method: "POST", headers, body });
  const payload = (await res.json()) as Record<string, unknown>;
  if (!res.ok) {
    throw new Error(`Client Credentials が HTTP ${res.status} で失敗しました: ${JSON.stringify(payload)}`);
  }
  return {
    status: res.status,
    keys: Object.keys(payload).sort(),
    tokenType: typeof payload["token_type"] === "string" ? payload["token_type"] : "",
    // 利用者が関わらないフローなので、リフレッシュトークンは返りません（セッション 7）
    hasRefreshToken: "refresh_token" in payload,
    expiresIn: typeof payload["expires_in"] === "number" ? payload["expires_in"] : -1,
    scope: typeof payload["scope"] === "string" ? payload["scope"] : "",
    accessToken: typeof payload["access_token"] === "string" ? payload["access_token"] : "",
  };
}
