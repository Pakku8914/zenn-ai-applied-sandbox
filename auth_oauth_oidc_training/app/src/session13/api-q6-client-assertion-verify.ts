// セッション 13 問題 6: private_key_jwt の assertion を「認可サーバー側」で検証します。
// realm は変えません。認可サーバーがやっていることを自分の手で再現するのが目的です。
import { importJWK, jwtVerify } from "jose";
import type { JWK, JWTPayload } from "jose";
import { audiencesOf } from "../session10/api-service-claims.js";

/** assertion の寿命の上限。長いほど、盗まれたときに使える時間が長くなります */
export const ASSERTION_MAX_LIFETIME_SECONDS = 300;
/** 受け付ける署名方式。HS256（共有秘密）は private_key_jwt では認めません */
export const ACCEPTED_ASSERTION_ALGS: readonly string[] = ["RS256", "ES256"];

export type AssertionRejection =
  | "malformed"
  | "alg_not_allowed"
  | "unknown_client"
  | "issuer_mismatch"
  | "audience_mismatch"
  | "expired"
  | "too_long_lived"
  | "jti_replayed"
  | "signature";

export type AssertionResult =
  | { readonly ok: true; readonly clientId: string; readonly jti: string }
  | { readonly ok: false; readonly reason: AssertionRejection };

export type AssertionContext = {
  /** クライアント ID から、登録済みの公開鍵を引ける表 */
  readonly keys: ReadonlyMap<string, JWK>;
  /** 自分が受け付ける宛先（トークンエンドポイントの URL や issuer） */
  readonly acceptedAudiences: readonly string[];
  readonly now: number;
  /** 使い終わった jti（"クライアント ID:jti" の形で覚えます） */
  readonly seenJtis?: Set<string>;
  /** フォームに入っていた client_id。assertion の iss と食い違えば拒否します */
  readonly formClientId?: string;
};

function decodePart(jwt: string, index: 0 | 1): Record<string, unknown> | undefined {
  const part = jwt.split(".")[index];
  if (part === undefined || part === "") return undefined;
  try {
    const decoded: unknown = JSON.parse(Buffer.from(part, "base64url").toString());
    if (typeof decoded !== "object" || decoded === null) return undefined;
    return decoded as Record<string, unknown>;
  } catch {
    return undefined;
  }
}

/** jose が投げたエラーの code を拒否の理由に対応づけます（セッション 4 の rejectReason と同じ作法） */
function rejectionFor(err: unknown): AssertionRejection {
  const code = (err as { code?: unknown }).code;
  if (code === "ERR_JWT_EXPIRED") return "expired";
  if (code === "ERR_JWT_CLAIM_VALIDATION_FAILED") return "issuer_mismatch";
  return "signature";
}

export async function verifyClientAssertion(assertion: string, ctx: AssertionContext): Promise<AssertionResult> {
  const header = decodePart(assertion, 0);
  const claimed = decodePart(assertion, 1);
  if (header === undefined || claimed === undefined) return { ok: false, reason: "malformed" };

  // 1. 方式の固定。ヘッダの alg を信じるのではなく、こちらが受け付ける方式だけを許します
  const alg = header["alg"];
  if (typeof alg !== "string") return { ok: false, reason: "malformed" };
  if (!ACCEPTED_ASSERTION_ALGS.includes(alg)) return { ok: false, reason: "alg_not_allowed" };

  // 2. 名乗り。iss と sub は同じクライアント ID でなければなりません
  const iss = claimed["iss"];
  if (typeof iss !== "string" || iss === "") return { ok: false, reason: "malformed" };
  if (claimed["sub"] !== iss) return { ok: false, reason: "issuer_mismatch" };
  if (ctx.formClientId !== undefined && ctx.formClientId !== iss) return { ok: false, reason: "issuer_mismatch" };

  // 3. 鍵の選択。ここまでは「主張」なので、鍵を引くためだけに使います
  const jwk = ctx.keys.get(iss);
  if (jwk === undefined) return { ok: false, reason: "unknown_client" };

  // 4. 署名と時刻。ここを通って初めて、中身を信用してよくなります
  let payload: JWTPayload;
  try {
    const key = await importJWK(jwk, alg);
    payload = (
      await jwtVerify(assertion, key, {
        algorithms: [alg],
        issuer: iss,
        subject: iss,
        currentDate: new Date(ctx.now * 1000),
        clockTolerance: 5,
      })
    ).payload;
  } catch (err) {
    return { ok: false, reason: rejectionFor(err) };
  }

  // 5. 宛先。自分宛てでない assertion は、別の認可サーバーへの転用を意味します
  if (!audiencesOf(payload).some((audience) => ctx.acceptedAudiences.includes(audience))) {
    return { ok: false, reason: "audience_mismatch" };
  }

  // 6. 寿命。短命であることを要求します
  if (typeof payload.exp !== "number") return { ok: false, reason: "malformed" };
  if (typeof payload.iat === "number" && payload.exp - payload.iat > ASSERTION_MAX_LIFETIME_SECONDS) {
    return { ok: false, reason: "too_long_lived" };
  }

  // 7. 一度きり。同じ jti の 2 回目を拒みます（クライアントごとに分けて覚えます）
  const jti = payload.jti;
  if (typeof jti !== "string" || jti === "") return { ok: false, reason: "malformed" };
  if (ctx.seenJtis !== undefined) {
    const seenKey = `${iss}:${jti}`;
    if (ctx.seenJtis.has(seenKey)) return { ok: false, reason: "jti_replayed" };
    ctx.seenJtis.add(seenKey);
  }

  return { ok: true, clientId: iss, jti };
}
