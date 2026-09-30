import { isRegressed, type BudgetRecord, type Metric } from '../budget.ts';

export type Regression = { metric: Metric; from: BudgetRecord; to: BudgetRecord };

/**
 * 問題7：履歴（古い順）をたどり、指標が最初に「要確認」の増え方をした記録を返す。
 * 値の無い記録は飛ばし、直前に値のあった記録と比べる。見つからなければ undefined。
 */
export function findFirstRegression(history: readonly BudgetRecord[], metric: Metric): Regression | undefined {
  let previous: BudgetRecord | undefined;
  for (const record of history) {
    const value = record.median[metric];
    if (value === undefined) continue;
    const before = previous?.median[metric];
    if (previous !== undefined && before !== undefined && isRegressed(metric, before, value)) {
      return { metric, from: previous, to: record };
    }
    previous = record;
  }
  return undefined;
}
