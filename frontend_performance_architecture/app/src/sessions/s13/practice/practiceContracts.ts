/**
 * 練習問題の型の契約（実行しない。どこからも import しない）。
 * @ts-expect-error の次の行が型エラーにならなくなったら、tsc --noEmit が失敗する。
 */
import type { Product } from '../../../data/products';
import { productColumns } from './productColumns';
import type { Column } from './SimpleTable';
import type { StockStatus } from './StockBadge';

// 問題2：few には remaining が必要
// @ts-expect-error remaining の無い few は作れない
export const fewWithoutCount: StockStatus = { kind: 'few' };

// 問題2：売り切れに残り数は持たせない
// @ts-expect-error soldOut は remaining を受け取らない
export const soldOutWithCount: StockStatus = { kind: 'soldOut', remaining: 0 };

// 問題7：satisfies なら、定義していない列名はその場で型エラーになる
// @ts-expect-error stock という列は定義していない
export const missingColumn = productColumns.stock;

// 問題7：型注釈で Record<string, …> にすると、どの列名でも通ってしまう（undefined かもしれない値になる）
const annotated: Record<string, Column<Product>> = productColumns;
export const silentlyUndefined: Column<Product> | undefined = annotated.stock;

// 問題7：render の引数は Product として推論される
// @ts-expect-error Product に stock は無い
export const wrongField = { header: '在庫', render: (p) => p.stock } satisfies Column<Product>;
