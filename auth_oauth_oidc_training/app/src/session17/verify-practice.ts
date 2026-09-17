// セッション 17 練習問題の解答を検証するスクリプト。
// Keycloak には一切アクセスしません（ネットワークに出ない検証です）。
// 期待値と一致しなければ非 0 で終了します。
import { attribute, hasFlag, parseSetCookie } from "../session03/web-app-cookie-tools.js";
import {
  EXPECTED_ORIGIN,
  RP_ID,
  buildAuthenticatorData,
  buildClientDataJson,
} from "./bookstore-webauthn.js";
import type { AccountAuthMethods, StoredCredential } from "./bookstore-webauthn.js";
import { createAuthenticator } from "./authenticator-stub.js";
import { verifyRegistration } from "./rp-webauthn-verify.js";
import { BYTE_LAYOUT, coverageReport, describeSignedInput, isCovered } from "./rp-q1-signed-input.js";
import { CHECK_ORDER, allAgree, predictReason, runMatrix } from "./rp-q2-check-matrix.js";
import type { BrokenPart } from "./rp-q2-check-matrix.js";
import { attemptForgery, breachReport, impactOf } from "./rp-q3-breach-report.js";
import { createPasskeyApp, toAssertionBody } from "./rp-q4-passkey-login.js";
import {
  DEFAULT_RETIRE_POLICY,
  canRetirePassword,
  fleetReport,
  migrationStage,
  nextStep,
  retireBlockers,
} from "./rp-q5-migration-plan.js";
import { blastRadius, hardeningPlan, requiresStepUp, simulateSyncedClone } from "./rp-q6-sync-risk.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

const jsonPost = (body: unknown) => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

console.log("=== セッション 17 練習問題の検証 ===\n");

// 問題 1: 署名対象の内訳
console.log("問題 1: 署名対象の内訳");
const authData = buildAuthenticatorData({ rpId: RP_ID, signCount: 3 });
const clientDataJson = buildClientDataJson({
  type: "webauthn.get",
  challenge: "Y2hhbGxlbmdl",
  origin: EXPECTED_ORIGIN,
  crossOrigin: false,
});
const report = describeSignedInput(authData, clientDataJson);
check("署名対象の合計", report.totalBytes, 69);
check("内訳は 4 つ", report.parts.length, 4);
check("内訳の合計と一致する", report.matchesLayout, true);
check("内訳のバイト数", BYTE_LAYOUT.map((part) => part.bytes), [32, 1, 4, 32]);
check("origin は署名対象に入る", isCovered("origin"), true);
check("challenge は署名対象に入る", isCovered("challenge"), true);
check("Cookie は署名対象に入らない", isCovered("cookie"), false);
check("User-Agent は署名対象に入らない", isCovered("userAgent"), false);
check("報告は 9 行", coverageReport().length, 9);
check("報告の 1 行目", coverageReport()[0], "origin: 署名対象に入る");
check(
  "clientDataJSON が長くても署名対象は 69 バイト",
  describeSignedInput(
    authData,
    buildClientDataJson({
      type: "webauthn.get",
      challenge: "Y2hhbGxlbmdl",
      origin: "http://localhost:3100/very/long/path/does/not/matter",
      crossOrigin: true,
    }),
  ).totalBytes,
  69,
);

// 問題 2: 検証の順序
console.log("\n問題 2: 検証の順序");
check("検査は 8 つ", CHECK_ORDER.length, 8);
check("最初の検査", CHECK_ORDER[0]?.id, "client-data-readable");
check("最後の検査", CHECK_ORDER[7]?.id, "signature");
check("壊れていなければ ok", predictReason([]), "ok");
check("origin だけ壊す", predictReason(["origin"]), "origin_mismatch");
check("origin と RP ID を壊すと origin が先", predictReason(["origin", "rp-id"]), "origin_mismatch");
check("署名だけ壊す", predictReason(["signature"]), "bad_signature");
check("本人確認と署名を壊すと本人確認が先", predictReason(["user-verification", "signature"]), "user_not_verified");

const CASES: readonly (readonly BrokenPart[])[] = [
  [],
  ["origin"],
  ["origin", "rp-id"],
  ["rp-id"],
  ["user-verification"],
  ["challenge"],
  ["ceremony-type", "challenge"],
  ["sign-count", "signature"],
  ["signature"],
];
const rows = runMatrix(CASES);
check("行数", rows.length, 9);
check("予測と実測がすべて一致", allAgree(rows), true);
check(
  "実測の並び",
  rows.map((row) => row.actual),
  [
    "ok",
    "origin_mismatch",
    "origin_mismatch",
    "rp_id_mismatch",
    "user_not_verified",
    "unknown_challenge",
    "wrong_ceremony_type",
    "sign_count_not_increasing",
    "bad_signature",
  ],
);

// 問題 3: 漏れたときに何ができるか
console.log("\n問題 3: 漏れたときに何ができるか");
check("パスワードハッシュは手元で当てられる", impactOf("password-hash").canGuessOffline, true);
check("公開鍵は手元で当てられない", impactOf("public-key").canGuessOffline, false);
check("パスワードは他サイトでも試せる", impactOf("password-hash").reusableOnOtherSites, true);
check("公開鍵は他サイトでは使えない", impactOf("public-key").reusableOnOtherSites, false);
check("パスワードは利用者から引き出せる", impactOf("password-hash").phishable, true);
check("公開鍵は利用者から引き出せない", impactOf("public-key").phishable, false);
check("どちらも盗んだだけでは即席で使えない", impactOf("password-hash").canImpersonateImmediately, false);
check("報告は 2 行", breachReport().length, 2);
const forgery = attemptForgery();
check("公開鍵だけを盗んだ攻撃者の assertion", forgery.reason, "bad_signature");
check("攻撃者の鍵は保管された公開鍵と別物", forgery.signatureValidForStolenKey, false);

// 問題 4: HTTP に組み込む
console.log("\n問題 4: HTTP に組み込む");
const passkey = createPasskeyApp();
const laptop = createAuthenticator({ deviceLabel: "alice-laptop" });
const registerCeremony = passkey.challenges.start("webauthn.create", "alice-sub");
check(
  "テスト用の登録",
  verifyRegistration(
    laptop.register({ challenge: registerCeremony.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    passkey.challenges,
    passkey.credentials,
    { deviceLabel: "alice-laptop" },
  ).ok,
  true,
);

const startRes = await passkey.app.request("/passkey/login/start", jsonPost({ userId: "alice-sub" }));
const startBody = (await startRes.json()) as {
  challenge: string;
  rpId: string;
  origin: string;
  allowCredentials: string[];
};
check("start は 200", startRes.status, 200);
check("キャッシュさせない", startRes.headers.get("cache-control"), "no-store");
check("allowCredentials は 1 件", startBody.allowCredentials.length, 1);
check("rpId を返す", startBody.rpId, RP_ID);

const unknownRes = await passkey.app.request("/passkey/login/start", jsonPost({ userId: "nobody" }));
const unknownBody = (await unknownRes.json()) as { allowCredentials: string[] };
check("知らない利用者でも 200", unknownRes.status, 200);
check("知らない利用者の allowCredentials は空", unknownBody.allowCredentials, []);

const assertion = laptop.assert({
  challenge: startBody.challenge,
  origin: startBody.origin,
  rpId: startBody.rpId,
});
const finishRes = await passkey.app.request("/passkey/login/finish", jsonPost(toAssertionBody(assertion)));
const finishBody = (await finishRes.json()) as { userId?: string; signCount?: number };
check("finish は 200", finishRes.status, 200);
check("ログインした利用者", finishBody.userId, "alice-sub");
const cookie = parseSetCookie(finishRes.headers.get("set-cookie"));
check("Cookie の名前", cookie?.name, "sid");
check("HttpOnly が付く", cookie !== undefined && hasFlag(cookie, "HttpOnly"), true);
check("SameSite", cookie === undefined ? "" : attribute(cookie, "SameSite"), "Lax");

const phishStart = await passkey.app.request("/passkey/login/start", jsonPost({ userId: "alice-sub" }));
const phishBody = (await phishStart.json()) as { challenge: string };
const phished = laptop.assert({
  challenge: phishBody.challenge,
  origin: "http://localhost:3999", // 偽サイト
  rpId: RP_ID,
});
const phishRes = await passkey.app.request("/passkey/login/finish", jsonPost(toAssertionBody(phished)));
check("偽オリジンは 401", phishRes.status, 401);
check("理由を返す", ((await phishRes.json()) as { error: string }).error, "origin_mismatch");
check("失敗時は Cookie を出さない", phishRes.headers.get("set-cookie"), null);

const malformedRes = await passkey.app.request("/passkey/login/finish", jsonPost({ credentialId: "x" }));
check("項目が欠けていたら 400", malformedRes.status, 400);

// 問題 5: 併存と移行
console.log("\n問題 5: 併存と移行");
function credentialFor(userId: string, deviceLabel: string, synced = false): StoredCredential {
  return { credentialId: `${userId}-${deviceLabel}`, userId, publicJwk: {}, signCount: 0, deviceLabel, synced };
}
const onlyPassword: AccountAuthMethods = {
  userId: "u1",
  passwordHash: "$argon2id$...",
  credentials: [],
  recoveryCodesLeft: 0,
};
const oneKey: AccountAuthMethods = {
  userId: "u2",
  passwordHash: "$argon2id$...",
  credentials: [credentialFor("u2", "laptop")],
  recoveryCodesLeft: 3,
};
const twoKeysSameDevice: AccountAuthMethods = {
  userId: "u3",
  passwordHash: "$argon2id$...",
  credentials: [credentialFor("u3", "laptop"), credentialFor("u3", "laptop")],
  recoveryCodesLeft: 3,
};
const twoDevices: AccountAuthMethods = {
  userId: "u4",
  passwordHash: "$argon2id$...",
  credentials: [credentialFor("u4", "laptop"), credentialFor("u4", "phone", true)],
  recoveryCodesLeft: 2,
};
const noRecovery: AccountAuthMethods = { ...twoDevices, userId: "u5", recoveryCodesLeft: 0 };
const done: AccountAuthMethods = { ...twoDevices, userId: "u6", passwordHash: null };

check("パスワードだけ", migrationStage(onlyPassword), "password-only");
check("1 本だけ登録", migrationStage(oneKey), "passkey-added");
check("2 本登録", migrationStage(twoDevices), "passkey-preferred");
check("パスワードが無い", migrationStage(done), "passwordless");
check("1 本ではまだ外せない", retireBlockers(oneKey), ["too-few-credentials", "single-device"]);
check("同じ端末に 2 本でも外せない", retireBlockers(twoKeysSameDevice), ["single-device"]);
check("回復手段が無いと外せない", retireBlockers(noRecovery), ["no-recovery"]);
check("2 台に分かれていれば外せる", canRetirePassword(twoDevices), true);
check("既にパスワードレス", retireBlockers(done), ["already-passwordless"]);
check("パスワードレスは外す対象ではない", canRetirePassword(done), false);
check("次の一手（パスワードだけ）", nextStep(onlyPassword), "パスキーの登録を促す（required action）");
check("次の一手（1 本だけ）", nextStep(oneKey), "2 本目のクレデンシャルを登録させる");
check("次の一手（同じ端末に 2 本）", nextStep(twoKeysSameDevice), "別の端末でもう 1 本登録させる");
check("次の一手（回復手段なし）", nextStep(noRecovery), "回復手段を用意する");
check(
  "次の一手（条件を満たした）",
  nextStep(twoDevices),
  "パスワードを外せる（先にログイン方法の案内を切り替える）",
);
check("既定の方針", DEFAULT_RETIRE_POLICY.minCredentials, 2);
check(
  "端末をまたぐ要求を外すと同じ端末 2 本でも外せる",
  canRetirePassword(twoKeysSameDevice, { ...DEFAULT_RETIRE_POLICY, requireDistinctDevices: false }),
  true,
);
const fleet = fleetReport([onlyPassword, oneKey, twoKeysSameDevice, twoDevices, noRecovery, done]);
check("段階ごとの人数", fleet.stages, {
  "password-only": 1,
  "passkey-added": 1,
  "passkey-preferred": 3,
  passwordless: 1,
});
check("外せる人数", fleet.retirable, 1);
check("詰まっている理由の内訳", fleet.blocked, {
  "already-passwordless": 1,
  "too-few-credentials": 2,
  "single-device": 3,
  "no-recovery": 2,
});

// 問題 6: 同期パスキーの帰結
console.log("\n問題 6: 同期パスキーの帰結");
const clone = simulateSyncedClone();
check("1 台目で 2 回ログインした後のサインカウント", clone.firstSignCount, 2);
check("2 台目が送ってくるサインカウント", clone.cloneSignCount, 1);
check("厳しく拒否する方針", clone.strictOutcome, "sign_count_not_increasing");
check("記録して通す方針", clone.flaggedOutcome, "ok");
check("巻き戻りを記録した", clone.flagged, true);
const radius = blastRadius([
  credentialFor("u4", "laptop"),
  credentialFor("u4", "phone", true),
  credentialFor("u7", "phone", true),
  credentialFor("u8", "yubikey"),
]);
check("同期パスキーの本数", radius.syncedCount, 2);
check("デバイス固定の本数", radius.deviceBoundCount, 2);
check("クラウド経由で狙われる利用者", radius.usersAtRiskFromCloud, ["u4", "u7"]);
check("同期パスキーで買い物はステップアップ", requiresStepUp("synced", "purchase"), true);
check("デバイス固定で買い物はそのまま", requiresStepUp("device-bound", "purchase"), false);
check("管理操作はどちらでもステップアップ", requiresStepUp("device-bound", "admin"), true);
check("同期パスキー × 買い物の手当て", hardeningPlan("synced", "purchase").length, 3);
check("デバイス固定 × 閲覧の手当て", hardeningPlan("device-bound", "read").length, 1);
check(
  "デバイス固定 × 管理操作の手当て",
  hardeningPlan("device-bound", "admin")[2],
  "管理操作にはデバイス固定のクレデンシャルを別に登録させる",
);

console.log(
  failures === 0
    ? "\nセッション 17 練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
