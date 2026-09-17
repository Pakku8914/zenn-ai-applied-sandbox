// セッション 4 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
import { jwtVerify } from "jose";
import { AUDIENCE, ISSUER, fetchAccessToken, fetchSigningKey } from "./bookstore-endpoints.js";
import { audienceList, decodeParts, lifetimeSeconds } from "./api-service-jwt-parts.js";
import { rejectReason, verifyAccessToken, verifyOptions } from "./api-service-verify-jwt.js";
import { verifyByHeaderAlg, verifyClaimsOnly } from "./api-service-verify-insecure.js";
import {
  forgeHs256Token,
  forgeNoneToken,
  mintTokenWithOwnKey,
  tamperPayload,
} from "./attacker-forge-tokens.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 検証が失敗することを確かめます。expectedReason を渡すと失敗理由まで照合します */
async function checkRejected(
  label: string,
  run: () => Promise<unknown>,
  expectedReason?: string,
): Promise<void> {
  try {
    await run();
    check(label, "通ってしまった", expectedReason ?? "拒否された");
  } catch (err) {
    const actual = expectedReason === undefined ? "拒否された" : rejectReason(err);
    check(label, actual, expectedReason ?? "拒否された");
  }
}

// 1. 本物のトークンの 3 部構成とクレーム（本文に載せた値と一致するか）
const token = await fetchAccessToken();
const signingKey = await fetchSigningKey();
const parts = decodeParts(token);

check("ピリオドで区切られた要素数", token.split(".").length, 3);
check("ヘッダの alg", parts.header["alg"], "RS256");
check("ヘッダの kid が JWKS の署名鍵と一致", parts.header["kid"] === signingKey.kid, true);
check("ペイロードの iss", parts.payload["iss"], ISSUER);
check("ペイロードの azp", parts.payload["azp"], "batch-worker");
check("aud に api-service を含む", audienceList(parts.payload).includes(AUDIENCE), true);
// batch-worker のトークンでは aud が配列で返る（サービスアカウントに account クライアントのロールが付くため）。
// 認可コードフローで発行されたトークンでは文字列になるので、検証側は必ず配列へ正規化する。
check("aud が配列で返るか（batch-worker の場合）", Array.isArray(parts.payload["aud"]), true);
check("aud に account も含まれるか", audienceList(parts.payload).includes("account"), true);
check("scope", parts.payload["scope"], "email profile");
check("有効期間（exp - iat）", lifetimeSeconds(parts.payload), 300);
check("署名部分が空でない", parts.signature.length > 0, true);
// 練習問題 1 の期待出力が「nbf: なし」であることの裏付け（任意のクレームなので実測で固定する）
check("アクセストークンに nbf が含まれない", parts.payload["nbf"] === undefined, true);

// 2. 正しい順序の検証が通ること
const verified = await verifyAccessToken(token);
check("厳格な検証後の alg", verified.protectedHeader.alg, "RS256");
check("厳格な検証後の azp", verified.payload["azp"], "batch-worker");

// 3. 失敗するべきケース（署名 → iss → aud → 時刻）
const tampered = tamperPayload(token, { sub: "attacker" });
await checkRejected("改ざんされたトークン", () => verifyAccessToken(tampered), "署名が鍵と一致しない");
check("デコードだけの検証は改ざんを見逃す", verifyClaimsOnly(tampered)["sub"], "attacker");

const wrongAudience = await mintTokenWithOwnKey({ issuer: ISSUER, audience: "other-service" });
await checkRejected(
  "宛先（aud）が違うトークン",
  () => jwtVerify(wrongAudience.token, wrongAudience.publicKey, verifyOptions),
  "クレームの検証に失敗（aud）",
);

const wrongIssuer = await mintTokenWithOwnKey({
  issuer: "http://evil.example.com/realms/bookstore",
  audience: AUDIENCE,
});
await checkRejected(
  "発行者（iss）が違うトークン",
  () => jwtVerify(wrongIssuer.token, wrongIssuer.publicKey, verifyOptions),
  "クレームの検証に失敗（iss）",
);

const expired = await mintTokenWithOwnKey({
  issuer: ISSUER,
  audience: AUDIENCE,
  issuedAtOffsetSec: -600,
  expiresInSec: 300,
});
await checkRejected(
  "有効期限が切れたトークン",
  () => jwtVerify(expired.token, expired.publicKey, verifyOptions),
  "有効期限が切れている",
);

const notYetValid = await mintTokenWithOwnKey({
  issuer: ISSUER,
  audience: AUDIENCE,
  notBeforeOffsetSec: 300,
  expiresInSec: 600,
});
await checkRejected(
  "まだ有効になっていない（nbf）トークン",
  () => jwtVerify(notYetValid.token, notYetValid.publicKey, verifyOptions),
  "クレームの検証に失敗（nbf）",
);

// 4. 実験用トークン発行ヘルパーが、指定どおりの標準クレームを入れているか
const lab = await mintTokenWithOwnKey({
  issuer: ISSUER,
  audience: AUDIENCE,
  subject: "lab-user",
  jti: "lab-0001",
  expiresInSec: 120,
  notBeforeOffsetSec: 0,
});
const labPayload = decodeParts(lab.token).payload;
check("実験用トークンの sub", labPayload["sub"], "lab-user");
check("実験用トークンの jti", labPayload["jti"], "lab-0001");
check("実験用トークンの iat のずれ", Number(labPayload["iat"]) - lab.baseTimeSec, 0);
check("実験用トークンの nbf のずれ", Number(labPayload["nbf"]) - lab.baseTimeSec, 0);
check("実験用トークンの exp のずれ", Number(labPayload["exp"]) - lab.baseTimeSec, 120);

// 5. alg: none 攻撃とアルゴリズム混同攻撃
const nowSec = Math.floor(Date.now() / 1000);
const forgedClaims = {
  iss: ISSUER,
  sub: "attacker",
  aud: AUDIENCE,
  iat: nowSec,
  exp: nowSec + 300,
  jti: "forged-0001",
};
const noneToken = forgeNoneToken(forgedClaims);
check(
  "alg: none は脆弱な検証を通ってしまう",
  (await verifyByHeaderAlg(noneToken, signingKey.modulus))["sub"],
  "attacker",
);
await checkRejected("alg: none は厳格な検証で拒否される", () => verifyAccessToken(noneToken));

const hs256Token = await forgeHs256Token(forgedClaims, signingKey.modulus, signingKey.kid);
check(
  "公開鍵を HMAC 鍵にした偽造は脆弱な検証を通ってしまう",
  (await verifyByHeaderAlg(hs256Token, signingKey.modulus))["sub"],
  "attacker",
);
await checkRejected("HS256 に差し替えた偽造は厳格な検証で拒否される", () =>
  verifyAccessToken(hs256Token),
);

// 6. 攻撃者が自分の鍵で署名したトークン
const ownKey = await mintTokenWithOwnKey({
  issuer: ISSUER,
  audience: AUDIENCE,
  subject: "attacker",
});
await checkRejected(
  "攻撃者が自分の鍵で署名したトークン",
  () => verifyAccessToken(ownKey.token),
  "署名に使われた鍵が JWKS に無い",
);

console.log(
  failures === 0
    ? "\nセッション 4 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
