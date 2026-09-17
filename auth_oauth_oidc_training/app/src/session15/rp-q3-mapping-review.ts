// 問題1（セッション15 後半）: 属性マッピングの定義を査読する。
// 「動くかどうか」ではなく「相手に何を決めさせているか」で危険を判定します。
import type { MappingRule, MappingTarget } from "./rp-attribute-mapping.js";

export type FindingCode =
  | "username-from-email"
  | "identifier-not-required"
  | "self-decided-from-claim"
  | "roles-never-revoked";

export type Finding = {
  readonly code: FindingCode;
  readonly target: MappingTarget;
  readonly message: string;
};

/** 相手に決めさせてはいけない属性 */
export const SELF_DECIDED: readonly MappingTarget[] = ["storeId", "roles"];
/** 利用者を指し続けるための属性。埋まらなければログインを失敗させる */
export const IDENTIFIERS: readonly MappingTarget[] = ["username", "email"];

/** 1 つの定義を査読します。判定の順序は固定です（毎回同じ順序で出ないと差分が読めません） */
export function reviewRule(rule: MappingRule): readonly Finding[] {
  const findings: Finding[] = [];

  if (rule.target === "username" && rule.source === "claim" && rule.from === "email") {
    findings.push({
      code: "username-from-email",
      target: rule.target,
      message: "メールアドレスは変わる。不変の識別子（sub / preferred_username）から写す",
    });
  }
  if (IDENTIFIERS.includes(rule.target) && !rule.required) {
    findings.push({
      code: "identifier-not-required",
      target: rule.target,
      message: "識別に使う属性が任意。空のまま利用者が作られてしまう",
    });
  }
  if (SELF_DECIDED.includes(rule.target) && rule.source === "claim") {
    findings.push({
      code: "self-decided-from-claim",
      target: rule.target,
      message: "相手が名乗った値をそのまま採っている。こちらで決めるか許可リストを通す",
    });
  }
  if (rule.target === "roles" && rule.onUpdate === "first-login-only") {
    findings.push({
      code: "roles-never-revoked",
      target: rule.target,
      message: "初回の権限が残り続ける。異動・退職で権限が剥奪されない",
    });
  }
  return findings;
}

export const reviewRules = (rules: readonly MappingRule[]): readonly Finding[] => rules.flatMap(reviewRule);

export const isSafe = (rules: readonly MappingRule[]): boolean => reviewRules(rules).length === 0;

export function reviewTable(rules: readonly MappingRule[]): string {
  const lines = ["| 対象 | 指摘 | 内容 |", "| :--- | :--- | :--- |"];
  const findings = reviewRules(rules);
  if (findings.length === 0) {
    lines.push("| - | 指摘なし | - |");
  }
  for (const finding of findings) {
    lines.push(`| ${finding.target} | ${finding.code} | ${finding.message} |`);
  }
  return lines.join("\n");
}

/** 査読の対象。提携先から送られてきた「これで動きました」という定義です */
export const RISKY_MAPPING: readonly MappingRule[] = [
  { target: "username", source: "claim", from: "email", required: true, onUpdate: "overwrite" },
  { target: "email", source: "claim", from: "email", required: false, onUpdate: "overwrite" },
  { target: "storeId", source: "claim", from: "storeId", required: true, onUpdate: "overwrite" },
  { target: "roles", source: "claim", from: "roles", required: false, onUpdate: "first-login-only" },
];

/** 指摘をすべて潰した定義。reviewRules(SAFE_MAPPING) が空になることが合格条件です */
export const SAFE_MAPPING: readonly MappingRule[] = [
  { target: "username", source: "claim", from: "preferred_username", required: true, onUpdate: "first-login-only" },
  { target: "email", source: "claim", from: "email", required: true, onUpdate: "overwrite" },
  { target: "storeId", source: "constant", from: "ueno", required: true, onUpdate: "first-login-only" },
  { target: "roles", source: "group-to-role", from: "groups", required: false, onUpdate: "overwrite" },
];
