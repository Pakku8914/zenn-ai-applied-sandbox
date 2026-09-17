// セッション 13（前半）問題 5: private_key_jwt の assertion を組み立て、
// 寿命が長すぎるものを「送る前に」自分で弾きます。
import { SignJWT, generateKeyPair } from "jose";
import { TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";
import { ASSERTION_ALG, CLIENT_ASSERTION_TYPE, createAssertionSigner } from "./batch-worker-private-key-jwt.js";
import { BATCH_CLIENT_ID } from "./batch-worker-client.js";

/** 1 つでも欠けたら送らないクレーム。iat は任意（無くても検証は成り立つ） */
export const REQUIRED_CLAIMS: readonly string[] = ["iss", "sub", "aud", "jti", "exp"];

/** 寿命の上限（秒）。1 回のトークン要求のためだけに作るので短くします */
export const ASSERTION_LIFETIME_LIMIT = 300;

export type LifetimeVerdict = "ok" | "too_long_lived" | "missing_exp" | "missing_iat" | "malformed";

/** 署名前のペイロード。ここでは「自分が作ったものを点検する」ために読みます */
export function claimsOf(assertion: string): Record<string, unknown> | undefined {
  const part = assertion.split(".")[1];
  if (part === undefined || part === "") return undefined;
  try {
    const decoded: unknown = JSON.parse(Buffer.from(part, "base64url").toString());
    return typeof decoded === "object" && decoded !== null ? (decoded as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

export function checkLifetime(assertion: string, limit: number = ASSERTION_LIFETIME_LIMIT): LifetimeVerdict {
  const claims = claimsOf(assertion);
  if (claims === undefined) return "malformed";
  const exp = claims["exp"];
  const iat = claims["iat"];
  if (typeof exp !== "number") return "missing_exp";
  if (typeof iat !== "number") return "missing_iat";
  // 「未来だから大丈夫」ではなく exp − iat で測ります
  return exp - iat > limit ? "too_long_lived" : "ok";
}

/** 必須クレームのうち入っていないものを、REQUIRED_CLAIMS の順に返します */
export function missingClaims(assertion: string): readonly string[] {
  const claims = claimsOf(assertion);
  if (claims === undefined) return REQUIRED_CLAIMS;
  return REQUIRED_CLAIMS.filter((claim) => claims[claim] === undefined);
}

/** 送るフォーム。client_secret がどこにも無いことが要点です */
export function buildAssertionForm(assertion: string, clientId: string = BATCH_CLIENT_ID): URLSearchParams {
  return new URLSearchParams({
    grant_type: "client_credentials",
    client_id: clientId,
    client_assertion_type: CLIENT_ASSERTION_TYPE,
    client_assertion: assertion,
  });
}

/** exp を入れ忘れた assertion をわざと自分の手で作ります（点検が効くことを確かめるため） */
async function buildWithoutExp(iat: number): Promise<string> {
  const { privateKey } = await generateKeyPair(ASSERTION_ALG, { extractable: true });
  return await new SignJWT({})
    .setProtectedHeader({ alg: ASSERTION_ALG })
    .setIssuer(BATCH_CLIENT_ID)
    .setSubject(BATCH_CLIENT_ID)
    .setAudience(TOKEN_ENDPOINT)
    .setJti("assertion-without-exp")
    .setIssuedAt(iat)
    .sign(privateKey); // setExpirationTime() を呼ばないだけ
}

export type AssertionAudit = {
  readonly label: string;
  readonly verdict: LifetimeVerdict;
  readonly missing: readonly string[];
  readonly sendable: boolean;
};

/** 3 本の assertion を作って点検します。送ってよいのは 1 本だけです */
export async function auditAssertions(now: number = Math.floor(Date.now() / 1000)): Promise<readonly AssertionAudit[]> {
  const signer = await createAssertionSigner();
  const candidates: ReadonlyArray<readonly [string, string]> = [
    ["寿命 60 秒（既定）", await signer.build({ iat: now, jti: "assertion-60s" })],
    ["寿命 3600 秒", await signer.build({ iat: now, jti: "assertion-3600s", lifetimeSeconds: 3600 })],
    ["exp を入れ忘れた", await buildWithoutExp(now)],
  ];
  return candidates.map(([label, assertion]) => {
    const verdict = checkLifetime(assertion);
    const missing = missingClaims(assertion);
    return { label, verdict, missing, sendable: verdict === "ok" && missing.length === 0 };
  });
}
