// 型のテスト（expectTypeOf）。本文8節に対応する。
// ここに書いた検証は実行時には何もせず、tsc --noEmit で確かめられる。
import { describe, expectTypeOf, it } from 'vitest';
import { buildPaymentSummary, calcShippingFee } from '../session16/pricing';
import type { PaymentSummary, Product } from '../session16/types';
import type { Product as CatalogProduct } from '../session17/catalog';
import { loadProducts } from '../session17/catalog';
import type { Result } from '../session18/result';
import { reserveStock } from '../session18/shop';
import type { Reservation, ShopError } from '../session18/shop';

/** 新規登録のときは id がまだ無い（セッション14で作った形） */
type ProductInput = Omit<Product, 'id'>;

describe('関数の型', () => {
  it('buildPaymentSummary の戻り値は PaymentSummary', () => {
    expectTypeOf(buildPaymentSummary).returns.toEqualTypeOf<PaymentSummary>();
  });

  it('calcShippingFee は数値を受け取って数値を返す', () => {
    expectTypeOf(calcShippingFee).parameter(0).toBeNumber();
    expectTypeOf(calcShippingFee).returns.toBeNumber();
  });

  it('loadProducts を await すると Product の配列になる', () => {
    expectTypeOf<Awaited<ReturnType<typeof loadProducts>>>().toEqualTypeOf<CatalogProduct[]>();
  });
});

describe('ユーティリティ型で作った型', () => {
  it('ProductInput からは id が消えている', () => {
    expectTypeOf<keyof ProductInput>().toEqualTypeOf<'name' | 'price' | 'stock' | 'categoryId'>();
  });

  it('PaymentSummary の payableAmount は数値', () => {
    expectTypeOf<PaymentSummary['payableAmount']>().toBeNumber();
  });
});

describe('Result と失敗のユニオン', () => {
  it('reserveStock の戻り値は成功と失敗のユニオン', () => {
    expectTypeOf(reserveStock).returns.toEqualTypeOf<Result<Reservation, ShopError>>();
  });

  it('ShopError から在庫不足だけを取り出せる', () => {
    expectTypeOf<Extract<ShopError, { kind: 'out_of_stock' }>>().toEqualTypeOf<{
      kind: 'out_of_stock';
      productName: string;
      requested: number;
      available: number;
    }>();
  });
});
