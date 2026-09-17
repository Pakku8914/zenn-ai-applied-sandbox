// セッション 17 の自己検証スクリプト。
// Keycloak には GET しか投げません（realm は 1 か所も書き換えません）。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。
import { createPublicKey, verify as verifySignature } from "node:crypto";
import { fetchAdminToken } from "../session16/bookstore-keys.js";
import {
  EXPECTED_ORIGIN,
  RP_ID,
  buildAuthenticatorData,
  buildClientDataJson,
  parseAuthenticatorData,
  parseClientDataJson,
  signatureBase,
  toBase64Url,
} from "./bookstore-webauthn.js";
import { createAuthenticator } from "./authenticator-stub.js";
import {
  CredentialStore,
  WebAuthnChallengeStore,
  verifyAssertion,
  verifyRegistration,
} from "./rp-webauthn-verify.js";
import {
  fetchWebAuthnAuthenticators,
  fetchWebAuthnPolicy,
  fetchWebAuthnRequiredActions,
} from "./admin-webauthn-policy.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 失敗の理由だけを取り出します（通ってしまった場合も 1 つの文字列で表せるように） */
function reasonOf(result: { readonly ok: true } | { readonly ok: false; readonly reason: string }): string {
  return result.ok ? "通ってしまった" : result.reason;
}

console.log("=== セッション 17 の検証 ===\n");

// 1. 署名対象の形（37 + 32 = 69 バイト）
console.log("1. 署名対象の形");
const sampleAuthData = buildAuthenticatorData({ rpId: RP_ID, signCount: 7 });
check("authenticatorData の長さ", sampleAuthData.length, 37);
const sampleParsed = parseAuthenticatorData(sampleAuthData);
check("RP ID のハッシュの長さ", sampleParsed?.rpIdHash.length, 32);
check("サインカウントを読み戻せる", sampleParsed?.signCount, 7);
check("ユーザー検証のフラグ", sampleParsed?.userVerified, true);
const sampleClientData = buildClientDataJson({
  type: "webauthn.get",
  challenge: "Y2hhbGxlbmdl",
  origin: EXPECTED_ORIGIN,
  crossOrigin: false,
});
check("署名対象の長さ", signatureBase(sampleAuthData, sampleClientData).length, 69);
check("clientDataJSON に origin が入っている", parseClientDataJson(sampleClientData)?.origin, EXPECTED_ORIGIN);
check("37 バイト未満は読めない", parseAuthenticatorData(sampleAuthData.subarray(0, 36)), undefined);

// 2. 登録の儀式
console.log("\n2. 登録の儀式（webauthn.create）");
const challenges = new WebAuthnChallengeStore();
const credentials = new CredentialStore();
const aliceKey = createAuthenticator({ deviceLabel: "alice-laptop" });

const registerCeremony = challenges.start("webauthn.create", "alice-sub");
const registration = verifyRegistration(
  aliceKey.register({ challenge: registerCeremony.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
  challenges,
  credentials,
  { deviceLabel: "alice-laptop" },
);
check("登録の検証", registration.ok, true);
check(
  "保管したのは公開鍵の 4 項目だけ",
  registration.ok ? Object.keys(registration.credential.publicJwk).sort() : [],
  ["crv", "kty", "x", "y"],
);
check("鍵の種類", registration.ok ? registration.credential.publicJwk["crv"] : "", "P-256");
check("誰の鍵かは challenge 側が決める", registration.ok ? registration.credential.userId : "", "alice-sub");
check("使い終わった challenge は残らない", challenges.size, 0);
check("クレデンシャルは 1 件", credentials.size, 1);

// 3. 認証の儀式（成功）
console.log("\n3. 認証の儀式（webauthn.get）");
const login1 = challenges.start("webauthn.get", "alice-sub");
const result1 = verifyAssertion(
  aliceKey.assert({ challenge: login1.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
  challenges,
  credentials,
);
check("正しい儀式は通る", result1.ok ? result1.userId : result1.reason, "alice-sub");
check("サインカウントが 1 進んだ", credentials.find(aliceKey.credentialId)?.signCount, 1);

// 4. フィッシング：偽サイトで得た署名は本物のサイトで通らない
console.log("\n4. フィッシング耐性（この章の山場）");
const FAKE_ORIGIN = "http://localhost:3999"; // ポートが違えば別のオリジン
const login2 = challenges.start("webauthn.get", "alice-sub");
const phished = aliceKey.assert({ challenge: login2.challenge, origin: FAKE_ORIGIN, rpId: RP_ID });
check("偽オリジンで署名した assertion", reasonOf(verifyAssertion(phished, challenges, credentials)), "origin_mismatch");
check("署名対象に偽のオリジンが入っている", parseClientDataJson(phished.clientDataJson)?.origin, FAKE_ORIGIN);
// 鍵は本物なので、署名そのものは正しい。それでも通らないのが公開鍵による認証の効き方です
const alicePublicKey = createPublicKey({ key: aliceKey.publicJwk, format: "jwk" });
check(
  "署名そのものは正しい（鍵は本物）",
  verifySignature(
    "sha256",
    signatureBase(phished.authenticatorData, phished.clientDataJson),
    alicePublicKey,
    phished.signature,
  ),
  true,
);

// 5. ほかの検査も 1 つずつ落としてみる（challenge は毎回新しく出す）
console.log("\n5. 検査を 1 つずつ落とす");
const login3 = challenges.start("webauthn.get", "alice-sub");
check(
  "RP ID を偽った assertion",
  reasonOf(
    verifyAssertion(
      aliceKey.assert({ challenge: login3.challenge, origin: EXPECTED_ORIGIN, rpId: "evil.example" }),
      challenges,
      credentials,
    ),
  ),
  "rp_id_mismatch",
);

const login4 = challenges.start("webauthn.get", "alice-sub");
check(
  "本人確認をしていない assertion",
  reasonOf(
    verifyAssertion(
      aliceKey.assert({
        challenge: login4.challenge,
        origin: EXPECTED_ORIGIN,
        rpId: RP_ID,
        userVerified: false,
      }),
      challenges,
      credentials,
    ),
  ),
  "user_not_verified",
);

const login5 = challenges.start("webauthn.get", "alice-sub");
const replayed = aliceKey.assert({ challenge: login5.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID });
check("1 回目は通る", verifyAssertion(replayed, challenges, credentials).ok, true);
check("同じ assertion の 2 回目", reasonOf(verifyAssertion(replayed, challenges, credentials)), "unknown_challenge");

check(
  "覚えのない challenge",
  reasonOf(
    verifyAssertion(
      aliceKey.assert({
        challenge: toBase64Url(Buffer.from("attacker-made-challenge")),
        origin: EXPECTED_ORIGIN,
        rpId: RP_ID,
      }),
      challenges,
      credentials,
    ),
  ),
  "unknown_challenge",
);

const mixedCeremony = challenges.start("webauthn.create", "alice-sub");
const registrationResponse = aliceKey.register({
  challenge: mixedCeremony.challenge,
  origin: EXPECTED_ORIGIN,
  rpId: RP_ID,
});
check(
  "登録の応答を認証として渡す",
  reasonOf(
    verifyAssertion(
      {
        credentialId: registrationResponse.credentialId,
        clientDataJson: registrationResponse.clientDataJson,
        authenticatorData: registrationResponse.authenticatorData,
        signature: Buffer.alloc(64),
      },
      challenges,
      credentials,
    ),
  ),
  "wrong_ceremony_type",
);

const strangerKey = createAuthenticator();
const login6 = challenges.start("webauthn.get", "alice-sub");
check(
  "登録していない認証器",
  reasonOf(
    verifyAssertion(
      strangerKey.assert({ challenge: login6.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
      challenges,
      credentials,
    ),
  ),
  "unknown_credential",
);

const login7 = challenges.start("webauthn.get", "alice-sub");
const tampered = aliceKey.assert({ challenge: login7.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID });
const brokenSignature = Buffer.from(tampered.signature);
brokenSignature[10] = (brokenSignature[10] ?? 0) ^ 0xff;
check(
  "署名を 1 バイト壊した assertion",
  reasonOf(verifyAssertion({ ...tampered, signature: brokenSignature }, challenges, credentials)),
  "bad_signature",
);

// サインカウントは「同じ値の 2 回目」で落ちます（別の認証器で確かめます）
const bobKey = createAuthenticator({ deviceLabel: "bob-phone" });
const bobRegister = challenges.start("webauthn.create", "bob-sub");
check(
  "bob の登録",
  verifyRegistration(
    bobKey.register({ challenge: bobRegister.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
    { deviceLabel: "bob-phone" },
  ).ok,
  true,
);
const bobLogin1 = challenges.start("webauthn.get", "bob-sub");
check(
  "bob の 1 回目",
  verifyAssertion(
    bobKey.assert({ challenge: bobLogin1.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
  ).ok,
  true,
);
const bobLogin2 = challenges.start("webauthn.get", "bob-sub");
check(
  "サインカウントが増えない 2 回目",
  reasonOf(
    verifyAssertion(
      bobKey.assert({ challenge: bobLogin2.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID, countStep: 0 }),
      challenges,
      credentials,
    ),
  ),
  "sign_count_not_increasing",
);

// 6. Keycloak 側の口を読む（realm は変更しません）
console.log("\n6. Keycloak 側の口を読む（GET のみ）");
const adminToken = await fetchAdminToken();
const policy = await fetchWebAuthnPolicy(adminToken);
check(
  "realm に WebAuthn の設定が 2 系統ある",
  policy.twoFactorKeys.length > 0 && policy.passwordlessKeys.length > 0,
  true,
);
const requiredActions = await fetchWebAuthnRequiredActions(adminToken);
const authenticators = await fetchWebAuthnAuthenticators(adminToken);
check("WebAuthn の登録口か認証部品が用意されている", requiredActions.length + authenticators.length >= 1, true);
console.log("   参考（本文では値を断定しません。ここに出るのがあなたの環境の値です）:");
for (const key of policy.passwordlessKeys) {
  console.log(`     ${key} = ${policy.values[key] ?? ""}`);
}
console.log(`     required actions = ${JSON.stringify(requiredActions)}`);
console.log(`     authenticators   = ${JSON.stringify(authenticators)}`);

console.log(
  failures === 0 ? "\nセッション 17 のすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
