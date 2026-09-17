// ID トークンを「認証の結果」として受け入れてよいかを判断します。
// 判断材料は 6 つ: 署名・iss・aud・時刻（exp）・nonce・azp。1 つでも省くと穴が開きます。
import { createRemoteJWKSet, jwtVerify } from "jose";
import type { JWTPayload } from "jose";
import { CLIENT_ID, ISSUER, JWKS_URI } from "./bookstore-oidc.js";

// JWKS の取得口は 1 回だけ作って使い回します（jose が取得結果をキャッシュします）
const jwks = createRemoteJWKSet(new URL(JWKS_URI));

/** ID トークンに求める条件。audience が「自分（RP）」である点がアクセストークンとの違いです */
export const idTokenVerifyOptions = {
  algorithms: ["RS256"], // ヘッダの alg を信じず、受け付ける方式を固定する
  issuer: ISSUER, // 誰が認証したのか
  audience: CLIENT_ID, // 誰に向けた認証結果なのか ＝ web-app 自身
  clockTolerance: 5, // 時計のずれの許容（秒）
};

/** 検証が通ったときにだけ組み立てる「ログインした人」の情報 */
export type Identity = {
  /** sub。表示名やメールが変わっても変わらない識別子。アプリ側の利用者 ID に紐付ける値 */
  readonly subject: string;
  /** preferred_username。表示用。あとから変わりうるので識別子には使わない */
  readonly username: string;
  readonly name: string;
  readonly email: string;
  readonly emailVerified: boolean;
  /** auth_time。実際に本人確認が行われた時刻（UNIX 秒） */
  readonly authTime: number;
  /** sid。認可サーバー側のセッション識別子 */
  readonly sessionId: string;
};

/** 受け入れられない理由を持った例外。理由はログ用で、利用者の画面には出しません */
export class IdTokenError extends Error {
  readonly reason: string;

  constructor(reason: string) {
    super(`ID トークンを受け入れられません: ${reason}`);
    this.reason = reason;
  }
}

// jose が投げるエラーの code を、日本語の短い理由に対応づけます
const REASONS: Record<string, string> = {
  ERR_JWS_SIGNATURE_VERIFICATION_FAILED: "署名が鍵と一致しない",
  ERR_JWT_EXPIRED: "有効期限が切れている",
  ERR_JWKS_NO_MATCHING_KEY: "署名に使われた鍵が JWKS に無い",
  ERR_JOSE_ALG_NOT_ALLOWED: "許可していない署名アルゴリズム",
  // 3 つの部分に分かれていない文字列は、署名を見る前に形式で落ちます
  ERR_JWS_INVALID: "JWT の形式ではない",
  ERR_JWT_INVALID: "JWT の形式ではない",
};

/** jose が投げたエラーを 1 行の理由に翻訳します（セッション 4 の rejectReason と同じ考え方） */
export function failureReason(err: unknown): string {
  const e = (typeof err === "object" && err !== null ? err : {}) as { code?: unknown; claim?: unknown };
  const code = typeof e.code === "string" ? e.code : "";
  if (code === "ERR_JWT_CLAIM_VALIDATION_FAILED") {
    return `${typeof e.claim === "string" ? e.claim : "不明"} が期待した値ではない`;
  }
  return REASONS[code] ?? `その他の失敗（${code === "" ? "コードなし" : code}）`;
}

const asString = (value: unknown): string => (typeof value === "string" ? value : "");

/** 署名・iss・aud・時刻を jose に任せます（ここまではアクセストークンの検証と同じ手順） */
async function verifySignatureAndClaims(idToken: string, audience: string): Promise<JWTPayload> {
  try {
    const { payload } = await jwtVerify(idToken, jwks, { ...idTokenVerifyOptions, audience });
    return payload;
  } catch (err) {
    throw new IdTokenError(failureReason(err));
  }
}

/**
 * ID トークンを検証して Identity を返します。
 * expectedNonce には、認可リクエストを始めたときに自分で保存しておいた nonce を渡します。
 */
export async function verifyIdToken(args: { idToken: string; expectedNonce: string }): Promise<Identity> {
  // 1〜4. 署名 → iss → aud → 時刻
  const payload = await verifySignatureAndClaims(args.idToken, CLIENT_ID);

  // 5. nonce。自分が始めたログインの応答であることを確かめます（使い回し対策）
  if (args.expectedNonce === "") {
    // 「トークンに nonce があるか」ではなく「保存した値と一致するか」を見るので、
    // 保存側が空なら照合そのものが成り立ちません
    throw new IdTokenError("保存していた nonce が無い（照合できない）");
  }
  if (asString(payload["nonce"]) !== args.expectedNonce) {
    throw new IdTokenError("nonce が一致しない（使い回しの可能性）");
  }

  // 6. azp。aud に複数のクライアントが並ぶ構成では、要求した本人かも確かめます
  const azp = asString(payload["azp"]);
  if (azp !== "" && azp !== CLIENT_ID) {
    throw new IdTokenError(`azp が ${CLIENT_ID} ではない（別のクライアント向けのトークン）`);
  }

  const subject = asString(payload.sub);
  if (subject === "") {
    throw new IdTokenError("sub が無い（誰の認証結果か分からない）");
  }

  return {
    subject,
    username: asString(payload["preferred_username"]),
    name: asString(payload["name"]),
    email: asString(payload["email"]),
    emailVerified: payload["email_verified"] === true,
    authTime: typeof payload["auth_time"] === "number" ? payload["auth_time"] : 0,
    sessionId: asString(payload["sid"]),
  };
}

/** 宛先（aud）を差し替えて検証を試す実験用。通れば "通った"、駄目なら理由を返します */
export async function verifyWithAudience(token: string, audience: string): Promise<string> {
  try {
    await verifySignatureAndClaims(token, audience);
    return "通った";
  } catch (err) {
    return err instanceof IdTokenError ? err.reason : String(err);
  }
}
