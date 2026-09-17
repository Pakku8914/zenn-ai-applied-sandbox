// レポートの文字列を組み立てるモジュール。
// 画面への出力はここでは行わない。文字列の配列を返すだけにしておくと、
// 文言そのものをテストで比べられる（セッション19 で学んだ「純粋関数はテストしやすい」）。

import { InvariantError } from '../session18/errors';
import type { Result } from '../session18/result';
import type { PipelineError, ProductReport } from './types';

/** 失敗1件を、利用者が次の行動を取れる1行にする */
export function describePipelineError(error: PipelineError): string {
  switch (error.kind) {
    case 'read_failed':
      return `${error.fileName} を読み込めません（${error.detail}）`;
    case 'timeout':
      return `${error.fileName} の読み込みが ${error.limitMs}ms を超えました`;
    case 'invalid_json':
      return `${error.fileName} が JSON として読めません（先頭: ${error.head}）`;
    case 'not_array':
      return `${error.fileName} が配列ではありません`;
    case 'missing_field':
      return `${error.fileName} の${error.index + 1}件目: ${error.field} がありません`;
    case 'invalid_type':
      return (
        `${error.fileName} の${error.index + 1}件目: ` +
        `${error.field} の値が不正です（${JSON.stringify(error.value)}）`
      );
    case 'out_of_range':
      return (
        `${error.fileName} の${error.index + 1}件目: ` +
        `${error.field} が範囲外です（${error.value}）`
      );
    case 'unknown_category':
      return `「${error.productName}」のカテゴリ（categoryId: ${error.categoryId}）がマスタにありません`;
    default: {
      // 失敗の種類を増やしたら、ここが型エラーになる（セッション12 の網羅性チェック）
      const exhaustive: never = error;
      throw new InvariantError(`未知の失敗です: ${JSON.stringify(exhaustive)}`);
    }
  }
}

/** 成功したときのレポート */
export function formatReport(report: ProductReport): string[] {
  return [
    '=== 商品データ取得レポート ===',
    ...report.rows.map(
      (row) =>
        `${row.categoryName}: ${row.count}件 / 在庫${row.stockQuantity}点 / ` +
        `在庫金額 ${row.stockValue}円`
    ),
    '---',
    `合計: ${report.totalCount}件 / 在庫${report.totalStockQuantity}点 / ` +
      `在庫金額 ${report.totalStockValue}円`,
    `平均単価: ${report.averagePrice}円`,
    `在庫切れ: ${report.soldOutNames.length === 0 ? '(なし)' : report.soldOutNames.join(' / ')}`,
  ];
}

/** 失敗したときのレポート。何件失敗したかを先に出す */
export function formatFailure(errors: readonly PipelineError[]): string[] {
  return [
    `=== 取得に失敗しました（${errors.length}件） ===`,
    ...errors.map((error) => `- ${describePipelineError(error)}`),
  ];
}

/** 成功も失敗も同じ「文字列の配列」に変換する。分岐はここで1回だけ */
export function formatOutcome(outcome: Result<ProductReport, PipelineError[]>): string[] {
  return outcome.kind === 'ok' ? formatReport(outcome.value) : formatFailure(outcome.error);
}
