import type { WindowRange } from '../windowing';

/**
 * S11 練習問題：行の高さがばらばらのときの表示範囲。
 * 各行の上端の位置（累積和）を先に作っておき、スクロール位置から二分探索で行を探す。
 * 1 回の計算は O(log n) なので、件数が 10 倍になっても計算量はほとんど増えない。
 */

/** offsets[i] は i 行目の上端の位置。長さは行数 + 1 で、最後の値が全体の高さ */
export function buildOffsets(heights: readonly number[]): number[] {
  const offsets = [0];
  for (const h of heights) {
    offsets.push((offsets[offsets.length - 1] ?? 0) + h);
  }
  return offsets;
}

/** offsets[i] >= y となる最小の i（無ければ offsets.length） */
function lowerBound(offsets: readonly number[], y: number): number {
  let lo = 0;
  let hi = offsets.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((offsets[mid] ?? Number.POSITIVE_INFINITY) < y) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** offsets[i] > y となる最小の i（無ければ offsets.length） */
function upperBound(offsets: readonly number[], y: number): number {
  let lo = 0;
  let hi = offsets.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((offsets[mid] ?? Number.POSITIVE_INFINITY) <= y) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function computeVariableWindow(
  offsets: readonly number[],
  viewportHeight: number,
  scrollTop: number,
  overscan: number,
): WindowRange {
  const itemCount = offsets.length - 1;
  if (itemCount <= 0) {
    return { start: 0, end: 0, paddingTop: 0, paddingBottom: 0, totalHeight: 0 };
  }
  const totalHeight = offsets[itemCount] ?? 0;
  const top = Math.min(Math.max(0, scrollTop), Math.max(0, totalHeight - viewportHeight));

  // 上端が top 以下の行のうち最後のもの＝表示枠の上端にかかっている行
  const firstVisible = Math.min(itemCount - 1, upperBound(offsets, top) - 1);
  // 上端が表示枠の下端以上になる最初の行＝見えていない最初の行
  const lastVisible = Math.min(itemCount, lowerBound(offsets, top + viewportHeight));

  const start = Math.max(0, firstVisible - overscan);
  const end = Math.min(itemCount, lastVisible + overscan);
  return {
    start,
    end,
    paddingTop: offsets[start] ?? 0,
    paddingBottom: totalHeight - (offsets[end] ?? totalHeight),
    totalHeight,
  };
}
