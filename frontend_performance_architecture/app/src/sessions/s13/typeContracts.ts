/**
 * 型の契約が「破れないこと」を確かめるファイル（実行しない。どこからも import しない）。
 * @ts-expect-error の次の行は、型エラーにならなければならない。
 * 契約が緩んでエラーが出なくなると、tsc --noEmit が「使われていない @ts-expect-error」で失敗する。
 */
import type { Product } from '../../data/products';
import { assertNever } from '../s10/requestState';
import type { ListMode } from './catalog/ProductListView';

const noop = (_id: number): void => {};

// 正しい使い方は通る
export const cartMode: ListMode = { kind: 'cart', onAdd: noop };

// @ts-expect-error cart モードには onAdd が必要
export const cartWithoutCallback: ListMode = { kind: 'cart' };

// @ts-expect-error 存在しないモード名は書けない
export const unknownMode: ListMode = { kind: 'carts', onAdd: noop };

export function nameOf(value: unknown): string {
  // @ts-expect-error unknown のままでは中身を読めない（型ガードで絞り込んでから読む）
  return value.name;
}

// @ts-expect-error category が足りない（Product に項目を足すと、検証の定義にも同じエラーが出る）
export const incompleteShape = { id: 'number', name: 'string', price: 'number' } satisfies Record<keyof Product, 'number' | 'string'>;

export function describeMode(mode: ListMode): string {
  switch (mode.kind) {
    case 'browse':
      return '閲覧';
    case 'cart':
      return 'カート';
    default:
      // @ts-expect-error compare を書き忘れているので、mode は never にならない
      return assertNever(mode);
  }
}
