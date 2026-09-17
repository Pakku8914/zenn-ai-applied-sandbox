import { createRemoteJWKSet, jwtVerify } from "jose";
import type { JWTPayload } from "jose";

const ISSUER = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";
const AUDIENCE = "api-service";
const REALM = "api-service";

// JWKS の取得口はモジュールの読み込み時に 1 回だけ作る（jose が結果をキャッシュする）
const jwks = createRemoteJWKSet(new URL(`${ISSUER}/protocol/openid-connect/certs`));

// 受け付けるのは Authorization: Bearer <token> の形だけ（RFC 6750 の b64token）
const BEARER = /^Bearer +([A-Za-z0-9\-._~+/]+=*)$/i;

export type ApiResponse = {
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: Record<string, unknown>;
};

type BearerError = "invalid_request" | "invalid_token";

/** 401。error を付けるのは「出してきたが受け付けられない」ときだけ（RFC 6750） */
function unauthorized(message: string, error?: BearerError, description?: string): ApiResponse {
  const params = [`realm="${REALM}"`];
  if (error !== undefined) params.push(`error="${error}"`, `error_description="${description ?? ""}"`);
  return {
    status: 401,
    headers: { "www-authenticate": `Bearer ${params.join(", ")}`, "cache-control": "no-store" },
    body: { error: error ?? "unauthenticated", message },
  };
}

/** 403。出し直しても結果は変わらないので WWW-Authenticate は付けない */
function forbidden(message: string): ApiResponse {
  return { status: 403, headers: { "cache-control": "no-store" }, body: { error: "forbidden", message } };
}

/** realm ロールを取り出す。クレームが無ければ「持っていない」と同じ扱いにする */
function realmRolesOf(payload: JWTPayload): string[] {
  const access: unknown = payload["realm_access"];
  if (typeof access !== "object" || access === null) return [];
  const roles: unknown = (access as Record<string, unknown>)["roles"];
  return Array.isArray(roles) ? roles.filter((role): role is string => typeof role === "string") : [];
}

/** 全注文の一覧を返す入口。Authorization ヘッダ 1 本だけを受け取る純粋な関数 */
export async function readAllOrders(authorization: string | undefined): Promise<ApiResponse> {
  const header = (authorization ?? "").trim();
  // 1. スキーム名を確認する。空や Basic は「Bearer の資格情報が無い」扱い
  if (header === "" || !/^Bearer($| )/i.test(header)) {
    return unauthorized("アクセストークンが必要です");
  }
  const token = BEARER.exec(header)?.[1];
  if (token === undefined) {
    const description = "The Authorization header is not in the Bearer <token> form";
    return unauthorized("Authorization ヘッダの形式が正しくありません", "invalid_request", description);
  }

  // 2. 署名 → iss → aud → 時刻。4 つのオプションを必ず指定する
  let payload: JWTPayload;
  try {
    const verified = await jwtVerify(token, jwks, {
      algorithms: ["RS256"],
      issuer: ISSUER,
      audience: AUDIENCE,
      clockTolerance: 5,
    });
    payload = verified.payload;
  } catch (err) {
    // 詳しい理由はログにだけ残す
    console.warn(`[api-service] 401 invalid_token: ${err instanceof Error ? err.message : String(err)}`);
    return unauthorized("アクセストークンを受け付けられません", "invalid_token", "The access token is not valid");
  }

  const sub = payload.sub;
  if (typeof sub !== "string" || sub === "") {
    return unauthorized("アクセストークンを受け付けられません", "invalid_token", "The token has no subject");
  }

  // 3. ここから先は認可。足りないのは権限なので 403
  if (!realmRolesOf(payload).includes("staff")) {
    return forbidden("全注文の閲覧には staff ロールが必要です");
  }
  return { status: 200, headers: { "cache-control": "no-store" }, body: { sub, total: 5 } };
}
