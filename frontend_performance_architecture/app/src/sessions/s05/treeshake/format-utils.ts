// 最上位に副作用のない（関数を定義しているだけの）モジュール。
// 使われない関数はビルド時に取り除ける。

export function formatPrice(yen: number): string {
  return `${new Intl.NumberFormat('ja-JP').format(yen)} 円`;
}

export function formatDate(epochMs: number): string {
  // '[format-date]' はバンドルに残ったかを検査する目印（verify-treeshake.ts が探す）
  return `[format-date] ${new Date(epochMs).toLocaleDateString('ja-JP')}`;
}

export function formatPoints(points: number): string {
  return `${points.toLocaleString('ja-JP')} pt`;
}
