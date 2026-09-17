// 問題3（セッション15 前半）: 信頼関係の材料が欠けたとき、連携が「どの段階で」失敗するかを分類する。
// 4 材料は同列ではありません。欠け方によって、気づくのが早いか遅いかが変わります。
import { TRUST_MATERIALS, checkTrust } from "./bookstore-sso-actors.js";
import type { TrustMaterial } from "./bookstore-sso-actors.js";

/** 連携が壊れる段階。配列の並びがそのまま「早い順」です */
export const STAGE_ORDER = ["setup", "authorize", "callback", "verify"] as const;
export type FailureStage = (typeof STAGE_ORDER)[number];

export const STAGE_LABELS: Readonly<Record<FailureStage, string>> = {
  setup: "設定を保存する前（IdP の登録そのものができない）",
  authorize: "認可リクエストを出すとき（送り先が決まらない）",
  callback: "IdP から戻ってくるとき（相手がこちらを見分けられない）",
  verify: "受け取った結果を検証するとき（署名を確かめられない）",
};

/** 材料 → それが欠けたときに最初に失敗する段階 */
export const FAILURE_STAGE: Readonly<Record<TrustMaterial, FailureStage>> = {
  "issuer-id": "setup",
  endpoints: "authorize",
  "client-registration": "callback",
  "signing-key": "verify",
};

/** 欠けたときに現場で見える症状。エラー画面の文言ではなく「どう見えるか」を書きます */
export const SYMPTOMS: Readonly<Record<TrustMaterial, string>> = {
  "issuer-id": "相手をどう呼ぶかが決まらず、設定の必須項目が埋まらない",
  endpoints: "ログインボタンを押しても、どこにも飛ばない（送り先が無い）",
  "client-registration": "相手のログイン画面までは出るが、戻り先が未登録だとして拒否される",
  "signing-key": "ログインは通ったように見えるのに、結果の署名を検証できず受け取れない",
};

export type StageFinding = {
  readonly kind: TrustMaterial;
  readonly label: string;
  readonly stage: FailureStage;
  readonly symptom: string;
};

const rank = (stage: FailureStage): number => STAGE_ORDER.indexOf(stage);

/**
 * 欠けている材料を「失敗する段階が早い順」に並べます。
 * 判定そのものは checkTrust() に任せ、ここは分類だけを足します。
 */
export function failureFindings(
  config: Readonly<Record<string, unknown>>,
  registeredClientId: string | undefined,
): readonly StageFinding[] {
  const findings = checkTrust(config, registeredClientId)
    .filter((check) => !check.satisfied)
    .map((check) => {
      const doc = TRUST_MATERIALS.find((material) => material.kind === check.kind);
      if (doc === undefined) {
        throw new Error(`説明の無い材料です: ${check.kind}`);
      }
      const stage = FAILURE_STAGE[check.kind];
      return { kind: check.kind, label: doc.label, stage, symptom: SYMPTOMS[check.kind] };
    });
  return [...findings].sort((a, b) => rank(a.stage) - rank(b.stage));
}

/** 最初につまずく段階。材料がそろっていれば "none" です */
export function earliestStage(findings: readonly StageFinding[]): FailureStage | "none" {
  const first = findings[0];
  return first === undefined ? "none" : first.stage;
}

/** 気づくのが最も遅い欠け方。ここが残っていると「動いたと思ったのに落ちる」状態になります */
export function latestStage(findings: readonly StageFinding[]): FailureStage | "none" {
  const last = findings[findings.length - 1];
  return last === undefined ? "none" : last.stage;
}

export function failureTable(
  config: Readonly<Record<string, unknown>>,
  registeredClientId: string | undefined,
): string {
  const lines = ["| 欠けている材料 | 失敗する段階 | 現場で見える症状 |", "| :--- | :--- | :--- |"];
  for (const finding of failureFindings(config, registeredClientId)) {
    lines.push(`| ${finding.label} | ${STAGE_LABELS[finding.stage]} | ${finding.symptom} |`);
  }
  return lines.join("\n");
}
