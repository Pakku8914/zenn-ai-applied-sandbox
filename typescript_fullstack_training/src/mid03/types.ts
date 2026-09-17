// 中間プロジェクト3「商品データ取得 CLI」の型だけを置くモジュール。
//
// このファイルは mid03 の他のファイルを1つも import しない。
// 依存の矢印の終着点にしておくと、循環参照が構造的に起きなくなる。

import type { CatalogItem, Category, Product } from '../session17/catalog';

// セッション17 で定義した3つの型は、このプロジェクトでもそのまま使う。
// ここで再 export しておくと、mid03 の各モジュールは types.ts だけを見れば済む。
export type { CatalogItem, Category, Product };

/** 読み込み（load.ts）で起きる失敗。判別タグは本書共通の kind */
export type LoadError =
  | { kind: 'read_failed'; fileName: string; detail: string }
  | { kind: 'timeout'; fileName: string; limitMs: number };

/** 検証（validate.ts）で起きる失敗 */
export type ValidationError =
  | { kind: 'invalid_json'; fileName: string; head: string }
  | { kind: 'not_array'; fileName: string }
  | { kind: 'missing_field'; fileName: string; index: number; field: string }
  | { kind: 'invalid_type'; fileName: string; index: number; field: string; value: unknown }
  | { kind: 'out_of_range'; fileName: string; index: number; field: string; value: number };

/** 変換（transform.ts）で起きる失敗 */
export type TransformError = {
  kind: 'unknown_category';
  productName: string;
  categoryId: number;
};

/** この CLI が起こしうる失敗の全体。8種類すべてを1つのユニオン型でまとめる */
export type PipelineError = LoadError | ValidationError | TransformError;

/** カテゴリ1つ分の集計結果 */
export type CategorySummary = {
  categoryName: string;
  count: number;
  stockQuantity: number;
  stockValue: number;
};

/** 集計（aggregate.ts）の結果。レポートに出す数値はすべてここに入っている */
export type ProductReport = {
  rows: CategorySummary[];
  totalCount: number;
  totalStockQuantity: number;
  totalStockValue: number;
  averagePrice: number;
  soldOutNames: string[];
};
