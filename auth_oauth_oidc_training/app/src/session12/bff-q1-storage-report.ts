// 問題 1 の解答: 3 つの要件を同時に満たす置き場所を探し、存在しないことを確かめます。
// 「どれが正解か」ではなく「何を諦めるか」を選ぶ問題だと分かるようにするのが目的です。
import { judgeAll } from "./bff-token-storage.js";
import type { StorageKind, StorageVerdict } from "./bff-token-storage.js";

/** どれも「できて当たり前」に見える 3 つの要件 */
export type Requirement = "survives-reload" | "not-stolen-by-xss" | "usable-from-script";

export const REQUIREMENTS: readonly Requirement[] = [
  "survives-reload",
  "not-stolen-by-xss",
  "usable-from-script",
];

export const REQUIREMENT_LABELS: Record<Requirement, string> = {
  "survives-reload": "リロードしてもログインが続く",
  "not-stolen-by-xss": "XSS があってもトークンを盗まれない",
  "usable-from-script": "ブラウザの JavaScript が Authorization ヘッダに載せられる",
};

export function satisfies(verdict: StorageVerdict, requirement: Requirement): boolean {
  if (requirement === "survives-reload") return !verdict.lostOnReload;
  if (requirement === "not-stolen-by-xss") return !verdict.stolenByXss;
  return verdict.usableFromScript;
}

export type RequirementRow = {
  readonly kind: StorageKind;
  readonly label: string;
  readonly met: readonly Requirement[];
  readonly unmet: readonly Requirement[];
};

export function evaluateRequirements(
  verdicts: readonly StorageVerdict[] = judgeAll(),
): readonly RequirementRow[] {
  return verdicts.map((verdict) => ({
    kind: verdict.kind,
    label: verdict.label,
    met: REQUIREMENTS.filter((requirement) => satisfies(verdict, requirement)),
    unmet: REQUIREMENTS.filter((requirement) => !satisfies(verdict, requirement)),
  }));
}

/** 3 つを同時に満たす置き場所を探します。空の配列が返るのが正解です */
export function impossibleTriangle(
  verdicts: readonly StorageVerdict[] = judgeAll(),
): readonly StorageKind[] {
  return evaluateRequirements(verdicts)
    .filter((row) => row.unmet.length === 0)
    .map((row) => row.kind);
}

/** 「この要件を諦めれば、この置き場所が使える」を引けるようにします */
export function optionsIfWeDrop(
  dropped: Requirement,
  verdicts: readonly StorageVerdict[] = judgeAll(),
): readonly StorageKind[] {
  const kept = REQUIREMENTS.filter((requirement) => requirement !== dropped);
  return verdicts
    .filter((verdict) => kept.every((requirement) => satisfies(verdict, requirement)))
    .map((verdict) => verdict.kind);
}

export function toMarkdown(rows: readonly RequirementRow[] = evaluateRequirements()): string {
  const header = "| 置き場所 | 満たす要件の数 | 満たせない要件 |";
  const rule = "| :--- | :--- | :--- |";
  const body = rows.map(
    (row) =>
      `| ${row.label} | ${row.met.length} / ${REQUIREMENTS.length} | ${
        row.unmet.length === 0 ? "なし" : row.unmet.map((r) => REQUIREMENT_LABELS[r]).join("、")
      } |`,
  );
  return [header, rule, ...body].join("\n");
}
