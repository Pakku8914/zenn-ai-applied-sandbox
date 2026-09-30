/**
 * 出発点 components/HeavyChart.tsx の buildPoints() と同じ計算。
 * 出発点のファイルは変更しない契約なので、分割・Worker 化のためにここへ写した。
 * 乱数を使わないため、どの版で計算しても点列は完全に一致する。
 */
export const ROWS = 100;
const INNER_LOOP = 200_000;

/** 1 点ぶん（出発点の外側ループ 1 周ぶん）の計算。分割するときの最小単位になる。 */
export function computeRow(i: number): number {
  let acc = 0;
  for (let j = 0; j < INNER_LOOP; j += 1) {
    acc = (acc + (i * j) % 97) % 150;
  }
  return acc;
}

/** 出発点と同じく、100 点を一気に計算する（Worker の中ではこれをそのまま使う）。 */
export function buildPointsSync(): number[] {
  const result: number[] = [];
  for (let i = 0; i < ROWS; i += 1) {
    result.push(computeRow(i));
  }
  return result;
}

/** 出発点の polyline と同じ書式の文字列にする。点列の一致を DOM の属性で比べるため。 */
export function toPolyline(points: readonly number[]): string {
  return points.map((y, x) => `${x * 6},${160 - y}`).join(' ');
}
