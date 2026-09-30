/**
 * 問題7：DOM に残す行を複数にする（フォーカス中の行に加えて、ダイアログを開いた行・編集中の行など）。
 * 範囲外の番号は無視し、重複を除いて番号順に返す。
 */
export function renderIndicesMany(start: number, end: number, pinned: readonly number[], count: number): number[] {
  const set = new Set<number>();
  for (let i = start; i < end; i += 1) set.add(i);
  for (const p of pinned) {
    if (Number.isInteger(p) && p >= 0 && p < count) set.add(p);
  }
  return [...set].sort((a, b) => a - b);
}
