// 問題 2 の解答: 候補の中から宛先を 1 つ選び、落選の理由まで説明できるようにします。
// 「安全そうだから」ではなく、順位の付いた基準のどこで差が付いたかで説明します。
import { classifyRedirectUri, matchesRegistration } from "./mobile-redirect.js";
import type { RedirectVerdict } from "./mobile-redirect.js";

/** 選定の基準。配列の先頭にあるものほど強く効きます */
export type Criterion = "ownership-verified" | "not-hijackable" | "exact-matchable";

export const CRITERIA: readonly Criterion[] = ["ownership-verified", "not-hijackable", "exact-matchable"];

export const CRITERION_FAILURES: Record<Criterion, string> = {
  "ownership-verified": "OS が宛先の所有関係を検証しない",
  "not-hijackable": "同じ宛先を名乗る別のアプリに横取りされうる",
  "exact-matchable": "認可サーバーに完全一致で登録できない",
};

export function meets(verdict: RedirectVerdict, criterion: Criterion): boolean {
  if (criterion === "ownership-verified") return verdict.ownershipVerified;
  if (criterion === "not-hijackable") return !verdict.hijackable;
  return verdict.exactMatchable;
}

/**
 * 満たした基準の「数」ではなく「順位」で点を付けます。
 * 上位の基準 1 つは、下位の基準すべてより重い（2 の累乗にしているのはそのためです）。
 */
export function scoreOf(verdict: RedirectVerdict): number {
  return CRITERIA.reduce(
    (total, criterion, index) => total + (meets(verdict, criterion) ? 2 ** (CRITERIA.length - index) : 0),
    0,
  );
}

/** なぜ選ばれなかったかを 1 行で説明します（最初に差が付いた基準を挙げる） */
export function rejectionReason(verdict: RedirectVerdict, chosen: RedirectVerdict): string {
  const criterion = CRITERIA.find((item) => meets(chosen, item) && !meets(verdict, item));
  if (criterion === undefined) {
    return "選ばれた候補と同点だが、登録するのは 1 つに絞る";
  }
  return `${CRITERION_FAILURES[criterion]}（${verdict.note}）`;
}

export type Choice = {
  readonly chosen: RedirectVerdict;
  readonly rejected: ReadonlyArray<{ readonly uri: string; readonly reason: string }>;
};

export function chooseRedirectUri(candidates: readonly string[]): Choice {
  const verdicts = candidates.map(classifyRedirectUri);
  // 同点のときは入力の順序を保つ（Array#sort は安定）
  const sorted = [...verdicts].sort((a, b) => scoreOf(b) - scoreOf(a));
  const chosen = sorted[0];
  if (chosen === undefined) {
    throw new Error("候補が 1 つもありません");
  }
  return {
    chosen,
    rejected: sorted.slice(1).map((verdict) => ({ uri: verdict.uri, reason: rejectionReason(verdict, chosen) })),
  };
}

/** 選んだ宛先を認可サーバーに登録したとき、何が通ってしまうかの照合表 */
export function registrationCheck(
  registered: string,
  requested: readonly string[],
): ReadonlyArray<{ readonly uri: string; readonly accepted: boolean }> {
  return requested.map((uri) => ({ uri, accepted: matchesRegistration(registered, uri) }));
}
