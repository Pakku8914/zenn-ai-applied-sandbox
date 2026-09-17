// 問題 4 の解答: 失効の速さと、そのために払う往復の回数を同時に見ます。
// 「全部イントロスペクションにする」は速いが高い。「全部ローカル検証」は安いが遅い。
// 操作の重さごとに分けるのが現実の答えになります（セッション 10 の併用判断の続きです）。
import type { RevocationInput } from "./api-service-revocation-policy.js";

/** 操作の重さ。API のルートごとにどれかを割り当てます */
export type Sensitivity = "read" | "write" | "admin";
export const SENSITIVITIES: readonly Sensitivity[] = ["read", "write", "admin"];

/** 重さごとに「手元で検証する」か「認可サーバーに聞く」かを決めた方針 */
export type HybridPolicy = Readonly<Record<Sensitivity, "local" | "introspect">>;

export type PolicyLevel = "none" | "admin" | "admin+write" | "all";
export const POLICY_LEVELS: readonly PolicyLevel[] = ["none", "admin", "admin+write", "all"];

export const POLICIES: Readonly<Record<PolicyLevel, HybridPolicy>> = {
  none: { read: "local", write: "local", admin: "local" },
  admin: { read: "local", write: "local", admin: "introspect" },
  "admin+write": { read: "local", write: "introspect", admin: "introspect" },
  all: { read: "introspect", write: "introspect", admin: "introspect" },
};

/**
 * その重さの操作で、失効が効くまでの最大の遅れ（秒）。
 * 手元で検証するなら寿命が切れるまで、聞くならキャッシュの分だけ遅れます。
 */
export function delaySeconds(level: PolicyLevel, sensitivity: Sensitivity, input: RevocationInput): number {
  return POLICIES[level][sensitivity] === "introspect"
    ? input.introspectionCacheSeconds
    : input.accessTokenLifespan;
}

/** 重さごとに 1 つ数値を持つ表 */
export type PerSensitivity = Readonly<Record<Sensitivity, number>>;
/** 1 秒あたりのリクエスト数（重さごと） */
export type TrafficMix = PerSensitivity;

/** 認可サーバーへ増える 1 秒あたりの問い合わせ回数 */
export function callsPerSecond(level: PolicyLevel, mix: TrafficMix): number {
  return SENSITIVITIES.filter((s) => POLICIES[level][s] === "introspect").reduce((sum, s) => sum + mix[s], 0);
}

export type WindowRequirement = {
  /** 重さごとの「何秒以内に効かなければならないか」 */
  readonly mustRevokeWithinSeconds: PerSensitivity;
  /** 1 秒あたり許せる問い合わせ回数（認可サーバーの容量） */
  readonly callBudgetPerSecond: number;
};

/** その方針で、すべての重さの遅れの要件を満たせるか */
export function meetsDelay(level: PolicyLevel, input: RevocationInput, req: WindowRequirement): boolean {
  return SENSITIVITIES.every((s) => delaySeconds(level, s, input) <= req.mustRevokeWithinSeconds[s]);
}

export type LevelChoice = {
  readonly level: PolicyLevel | "unsatisfiable";
  readonly calls: number;
  readonly reason: string;
};

/**
 * 遅れの要件と往復の予算の両方を満たす方針のうち、いちばん安いものを選びます。
 * 安い順に見るので、最初に見つかったものが答えです。
 */
export function chooseLevel(input: RevocationInput, req: WindowRequirement, mix: TrafficMix): LevelChoice {
  for (const level of POLICY_LEVELS) {
    const calls = callsPerSecond(level, mix);
    if (meetsDelay(level, input, req) && calls <= req.callBudgetPerSecond) {
      return { level, calls, reason: `遅れの要件を満たし、問い合わせは毎秒 ${calls} 回で予算内` };
    }
  }
  // 満たせない理由は 2 通りある。遅れ自体が無理なのか、遅れは満たせるが予算を超えるのか
  const needed = POLICY_LEVELS.find((level) => meetsDelay(level, input, req));
  if (needed === undefined) {
    return {
      level: "unsatisfiable",
      calls: 0,
      reason: "どの方針でも遅れの要件を満たせない。アクセストークンの寿命を短くする",
    };
  }
  return {
    level: "unsatisfiable",
    calls: callsPerSecond(needed, mix),
    reason: `要件を満たすには ${needed} が必要だが、問い合わせが予算を超える`,
  };
}

/** 「この重さの操作をどう検証するか」を 1 行で言います（手順書に添える説明） */
export function describe(level: PolicyLevel, sensitivity: Sensitivity): string {
  return POLICIES[level][sensitivity] === "introspect" ? "認可サーバーに聞く" : "手元で検証";
}
