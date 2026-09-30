/**
 * 横断復習①：計測結果の報告が「根拠として使える形か」を判定する。
 * 数値の良し悪しではなく、数値の取り方（条件・対象・回数・代表値・比較）だけを見る。
 */
export type ReportTarget = 'preview' | 'dev' | 'unknown';

export type MeasurementReport = {
  /** 計測したサーバー。preview＝本番ビルド、dev＝開発サーバー、unknown＝報告に書かれていない */
  target: ReportTarget;
  /** 計測条件。報告に書かれていなければ undefined */
  conditions?: { cpuThrottlingRate: number; downloadKbps: number; latencyMs: number };
  /** 計測した回数 */
  runs: number;
  /** 代表値の採り方 */
  aggregate: 'median' | 'mean' | 'single';
  /** 改善前後の比較を含む報告なら、両方を同じ条件で取ったと確認できるか */
  comparison?: { sameConditions: boolean };
};

export const MIN_RUNS = 3;

/** 報告の問題点を、見つかった順に返す。空配列なら根拠として使える。 */
export function trustIssues(report: MeasurementReport): string[] {
  const issues: string[] = [];
  if (report.conditions === undefined) issues.push('計測条件が書かれていない');
  if (report.target === 'dev') issues.push('開発サーバーを計測している');
  if (report.target === 'unknown') issues.push('本番ビルドを計測したか分からない');
  if (report.runs < MIN_RUNS) issues.push(`計測回数が ${MIN_RUNS} 回未満`);
  if (report.aggregate === 'mean') issues.push('平均を代表値にしている');
  if (report.comparison !== undefined && !report.comparison.sameConditions) {
    issues.push('改善前後を同じ条件で計測したと確認できない');
  }
  return issues;
}
