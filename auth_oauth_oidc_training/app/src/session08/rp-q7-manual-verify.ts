// 問題7 の解答。verifyIdToken() を使わず、jose の jwtVerify から 6 点の検証を自分で書きます。
// 本文の実装と同じ結果になることを確かめるのが目的です（ライブラリが何をしているかを手で再現する）。
import { createRemoteJWKSet, jwtVerify } from "jose";
import type { JWTPayload } from "jose";
import { CLIENT_ID, ISSUER, JWKS_URI } from "./bookstore-oidc.js";
import { failureReason } from "./rp-verify-id-token.js";

const jwks = createRemoteJWKSet(new URL(JWKS_URI));

const asString = (value: unknown): string => (typeof value === "string" ? value : "");

/** 検証の結果。成功なら sub、失敗なら理由を返します（本文の Identity / IdTokenError と対応） */
export type ManualResult = { ok: true; subject: string } | { ok: false; reason: string };

/**
 * 6 点を自分の手で確かめます。
 * 1〜4（署名・iss・aud・時刻）は jwtVerify のオプションで、5（nonce）と 6（azp）は自分で照合します。
 */
export async function manualVerifyIdToken(args: {
  idToken: string;
  expectedNonce: string;
}): Promise<ManualResult> {
  let payload: JWTPayload;
  try {
    // 1〜4. algorithms を固定し、iss・aud・時刻を jose に検証させる
    const verified = await jwtVerify(args.idToken, jwks, {
      algorithms: ["RS256"],
      issuer: ISSUER,
      audience: CLIENT_ID,
      clockTolerance: 5,
    });
    payload = verified.payload;
  } catch (err) {
    return { ok: false, reason: failureReason(err) };
  }

  // 5. nonce。「トークンに入っているか」ではなく「保存した値と一致するか」を見る
  if (args.expectedNonce === "") {
    return { ok: false, reason: "保存していた nonce が無い（照合できない）" };
  }
  if (asString(payload["nonce"]) !== args.expectedNonce) {
    return { ok: false, reason: "nonce が一致しない（使い回しの可能性）" };
  }

  // 6. azp。aud に複数のクライアントが並ぶ構成では、要求した本人かも確かめる
  const azp = asString(payload["azp"]);
  if (azp !== "" && azp !== CLIENT_ID) {
    return { ok: false, reason: `azp が ${CLIENT_ID} ではない（別のクライアント向けのトークン）` };
  }

  const subject = asString(payload.sub);
  if (subject === "") {
    return { ok: false, reason: "sub が無い（誰の認証結果か分からない）" };
  }
  return { ok: true, subject };
}
