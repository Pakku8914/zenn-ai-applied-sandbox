// セッション 17 練習問題 6（発展）: 同期パスキーとデバイス固定の差を、実測とリスク判断に落とす。
// 「鍵が端末から出ない」という前提が崩れると、サインカウントは何を意味するのかを確かめます。
import { EXPECTED_ORIGIN, RP_ID, parseAuthenticatorData } from "./bookstore-webauthn.js";
import type { StoredCredential } from "./bookstore-webauthn.js";
import { createAuthenticator } from "./authenticator-stub.js";
import {
  CredentialStore,
  WebAuthnChallengeStore,
  verifyAssertion,
  verifyRegistration,
} from "./rp-webauthn-verify.js";
import type { AssertionInput } from "./rp-webauthn-verify.js";

export type CredentialKind = "device-bound" | "synced";

export type RiskFacts = {
  readonly kind: CredentialKind;
  /** 秘密鍵が作られた端末の外に出るか */
  readonly keyLeavesDevice: boolean;
  /** 強度がクラウドアカウントの強度に依存するか */
  readonly dependsOnCloudAccount: boolean;
  /** サインカウントを「コピーの検出」に使えるか */
  readonly signCountTrustworthy: boolean;
  /** 端末を失ったときの回復のしかた */
  readonly lossRecovery: string;
};

export const RISK_FACTS: Readonly<Record<CredentialKind, RiskFacts>> = {
  "device-bound": {
    kind: "device-bound",
    keyLeavesDevice: false,
    dependsOnCloudAccount: false,
    signCountTrustworthy: true,
    lossRecovery: "失えば復元できない。別の端末にもう 1 本登録しておく以外に手はない",
  },
  synced: {
    kind: "synced",
    keyLeavesDevice: true,
    dependsOnCloudAccount: true,
    signCountTrustworthy: false,
    lossRecovery: "新しい端末に同じ鍵が降りてくる。ただしクラウドアカウントに入れることが前提",
  },
};

export type BlastRadius = {
  readonly syncedCount: number;
  readonly deviceBoundCount: number;
  /** クラウドアカウントを乗っ取られたら入られてしまう利用者 */
  readonly usersAtRiskFromCloud: readonly string[];
};

/**
 * 同期パスキーの影響範囲を数えます。
 * デバイス固定の鍵を別に持っていても、同期パスキー 1 本でログインできる設計なら
 * 弱い方が上限になります。だからここでは「同期が 1 本でもあれば対象」に数えます。
 */
export function blastRadius(credentials: readonly StoredCredential[]): BlastRadius {
  const synced = credentials.filter((credential) => credential.synced);
  return {
    syncedCount: synced.length,
    deviceBoundCount: credentials.length - synced.length,
    usersAtRiskFromCloud: [...new Set(synced.map((credential) => credential.userId))].sort(),
  };
}

export type CounterPolicy = "reject" | "flag";

export type PolicyOutcome = {
  /** 検証の結果（"ok" か理由コード） */
  readonly outcome: string;
  /** サインカウントの巻き戻りを記録したか */
  readonly flagged: boolean;
};

/**
 * サインカウントの扱いを方針として切り替えられる検証。
 * flag では、巻き戻りを「記録して通す」に格下げします（同期パスキーでは巻き戻りが起きるため）。
 * challenge は 1 回目の検証で使い捨てられるので、判断は verifyAssertion を呼ぶ前に済ませます。
 */
export function verifyWithCounterPolicy(
  input: AssertionInput,
  challenges: WebAuthnChallengeStore,
  credentials: CredentialStore,
  policy: CounterPolicy,
): PolicyOutcome {
  let flagged = false;
  if (policy === "flag") {
    const parsed = parseAuthenticatorData(input.authenticatorData);
    const credential = credentials.find(input.credentialId);
    if (parsed !== undefined && credential !== undefined && parsed.signCount <= credential.signCount) {
      flagged = true; // 「気づく」のがこの行の役目。止めるのは別の判断です
      credential.signCount = 0; // 巻き戻りを受け入れる
    }
  }
  const result = verifyAssertion(input, challenges, credentials);
  return { outcome: result.ok ? "ok" : result.reason, flagged };
}

export type CloneSimulation = {
  readonly firstSignCount: number;
  readonly cloneSignCount: number;
  readonly strictOutcome: string;
  readonly flaggedOutcome: string;
  readonly flagged: boolean;
};

/**
 * 同期パスキーが 2 台目の端末に降りてきた状況を再現します。
 * 2 台目は自分のカウンタを 0 から始めるので、サーバー側の記録より小さい値が届きます。
 */
export function simulateSyncedClone(): CloneSimulation {
  const challenges = new WebAuthnChallengeStore();
  const credentials = new CredentialStore();
  const device1 = createAuthenticator({ deviceLabel: "alice-laptop" });

  const register = challenges.start("webauthn.create", "alice-sub");
  verifyRegistration(
    device1.register({ challenge: register.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
    { deviceLabel: "alice-laptop", synced: true },
  );

  // 1 台目で 2 回ログインする
  for (let i = 0; i < 2; i += 1) {
    const pending = challenges.start("webauthn.get", "alice-sub");
    verifyAssertion(
      device1.assert({ challenge: pending.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
      challenges,
      credentials,
    );
  }
  const firstSignCount = credentials.find(device1.credentialId)?.signCount ?? -1;

  // クラウド経由で 2 台目に同じ秘密鍵が届く（本物のセキュリティキーには起こりません）
  const device2 = createAuthenticator({
    privateJwk: device1.exportPrivateJwk(),
    credentialId: device1.credentialId,
    signCount: 0,
    deviceLabel: "alice-phone",
  });

  const strictPending = challenges.start("webauthn.get", "alice-sub");
  const strict = verifyWithCounterPolicy(
    device2.assert({ challenge: strictPending.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
    "reject",
  );
  const cloneSignCount = device2.signCount;

  const flagPending = challenges.start("webauthn.get", "alice-sub");
  const flaggedResult = verifyWithCounterPolicy(
    device2.assert({ challenge: flagPending.challenge, origin: EXPECTED_ORIGIN, rpId: RP_ID }),
    challenges,
    credentials,
    "flag",
  );

  return {
    firstSignCount,
    cloneSignCount,
    strictOutcome: strict.outcome,
    flaggedOutcome: flaggedResult.outcome,
    flagged: flaggedResult.flagged,
  };
}

export type Operation = "read" | "purchase" | "admin";

const STEP_UP: Readonly<Record<CredentialKind, Readonly<Record<Operation, boolean>>>> = {
  "device-bound": { read: false, purchase: false, admin: true },
  synced: { read: false, purchase: true, admin: true },
};

/** その操作に、もう一度の本人確認（ステップアップ）を求めるか */
export function requiresStepUp(kind: CredentialKind, operation: Operation): boolean {
  return STEP_UP[kind][operation];
}

/** 種類と操作から、やるべきことを並べます */
export function hardeningPlan(kind: CredentialKind, operation: Operation): string[] {
  const plan: string[] = [];
  if (RISK_FACTS[kind].signCountTrustworthy) {
    plan.push("サインカウントの巻き戻りは拒否する（鍵は 1 台から出ないはず）");
  } else {
    plan.push("サインカウントは拒否の材料にせず、記録して監視する");
    plan.push("クラウドアカウント側の多要素認証を前提条件として案内する");
  }
  if (requiresStepUp(kind, operation)) {
    plan.push(`${operation} では直前のユーザー検証をもう一度求める`);
  }
  if (operation === "admin") {
    plan.push("管理操作にはデバイス固定のクレデンシャルを別に登録させる");
  }
  return plan;
}
