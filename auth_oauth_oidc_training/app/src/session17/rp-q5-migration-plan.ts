// セッション 17 練習問題 5: パスワードとパスキーの併存期間を設計し、
// 「パスワードを消せるのはいつか」を判断できる形にする。
import type { AccountAuthMethods } from "./bookstore-webauthn.js";

export type MigrationStage = "password-only" | "passkey-added" | "passkey-preferred" | "passwordless";

export type RetirePolicy = {
  /** 何本のクレデンシャルがあればパスワードを外せるか */
  readonly minCredentials: number;
  /** 別の端末にも登録されていることを要求するか */
  readonly requireDistinctDevices: boolean;
  /** 回復手段（1 回使い切りのコード）の最低残数 */
  readonly minRecoveryCodes: number;
};

export const DEFAULT_RETIRE_POLICY: RetirePolicy = {
  minCredentials: 2,
  requireDistinctDevices: true,
  minRecoveryCodes: 1,
};

/** 同じ利用者のクレデンシャルが、いくつの端末に散っているか */
function distinctDevices(account: AccountAuthMethods): number {
  return new Set(account.credentials.map((credential) => credential.deviceLabel)).size;
}

/** いまどの段階にいるか。1 本だけの状態を preferred と呼ばないのが要点です */
export function migrationStage(account: AccountAuthMethods): MigrationStage {
  if (account.passwordHash === null) return "passwordless";
  if (account.credentials.length === 0) return "password-only";
  return account.credentials.length >= 2 ? "passkey-preferred" : "passkey-added";
}

export type RetireBlocker = "already-passwordless" | "too-few-credentials" | "single-device" | "no-recovery";

/** パスワードを外せない理由。判定順を固定します（報告がいつでも同じ順に並ぶように） */
export function retireBlockers(
  account: AccountAuthMethods,
  policy: RetirePolicy = DEFAULT_RETIRE_POLICY,
): RetireBlocker[] {
  if (account.passwordHash === null) return ["already-passwordless"];
  const blockers: RetireBlocker[] = [];
  if (account.credentials.length < policy.minCredentials) blockers.push("too-few-credentials");
  if (policy.requireDistinctDevices && distinctDevices(account) < 2) blockers.push("single-device");
  if (account.recoveryCodesLeft < policy.minRecoveryCodes) blockers.push("no-recovery");
  return blockers;
}

export function canRetirePassword(account: AccountAuthMethods, policy: RetirePolicy = DEFAULT_RETIRE_POLICY): boolean {
  return account.passwordHash !== null && retireBlockers(account, policy).length === 0;
}

const NEXT_STEP: Readonly<Record<RetireBlocker, string>> = {
  "already-passwordless": "パスワードは既に無い。回復手段の残数を見る",
  "too-few-credentials": "2 本目のクレデンシャルを登録させる",
  "single-device": "別の端末でもう 1 本登録させる",
  "no-recovery": "回復手段を用意する",
};

/** その利用者に対して次に何をすべきか（1 文） */
export function nextStep(account: AccountAuthMethods, policy: RetirePolicy = DEFAULT_RETIRE_POLICY): string {
  if (migrationStage(account) === "password-only") return "パスキーの登録を促す（required action）";
  const first = retireBlockers(account, policy)[0];
  return first === undefined ? "パスワードを外せる（先にログイン方法の案内を切り替える）" : NEXT_STEP[first];
}

export type FleetReport = {
  readonly stages: Readonly<Record<MigrationStage, number>>;
  readonly retirable: number;
  readonly blocked: Readonly<Record<RetireBlocker, number>>;
};

/** 利用者全体の進み具合。移行は「全員が終わるまで終わらない」ので、集計が判断材料になります */
export function fleetReport(
  accounts: readonly AccountAuthMethods[],
  policy: RetirePolicy = DEFAULT_RETIRE_POLICY,
): FleetReport {
  const stages: Record<MigrationStage, number> = {
    "password-only": 0,
    "passkey-added": 0,
    "passkey-preferred": 0,
    passwordless: 0,
  };
  const blocked: Record<RetireBlocker, number> = {
    "already-passwordless": 0,
    "too-few-credentials": 0,
    "single-device": 0,
    "no-recovery": 0,
  };
  let retirable = 0;
  for (const account of accounts) {
    stages[migrationStage(account)] += 1;
    if (canRetirePassword(account, policy)) retirable += 1;
    for (const blocker of retireBlockers(account, policy)) blocked[blocker] += 1;
  }
  return { stages, retirable, blocked };
}
