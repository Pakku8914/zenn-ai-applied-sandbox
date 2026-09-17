// 問題7の解答：セッション18の buildReservations をテストで守る（型のテストつき）。
import { describe, expect, expectTypeOf, it, vi } from 'vitest';
import type { CatalogItem } from '../../session17/catalog';
import type { Result } from '../../session18/result';
import { buildReservations, describeShopError } from '../../session18/shop';
import type { Reservation, ShopError } from '../../session18/shop';
import { createCatalogLoader, createFailingLoader, withStock } from './q7-checkout';

describe('buildReservations（成功系）', () => {
  it('すべて成功すれば明細の配列を返す', async () => {
    // Arrange
    const loader = createCatalogLoader();

    // Act
    const result = await buildReservations(
      [
        { productId: 1, quantityInput: '2' },
        { productId: 3, quantityInput: '1' },
      ],
      loader
    );

    // Assert
    expect(result).toEqual({
      kind: 'ok',
      value: [
        { productId: 1, productName: 'ラベンダーの石けん', quantity: 2, lineTotal: 960 },
        { productId: 3, productName: 'マグカップ', quantity: 1, lineTotal: 2350 },
      ],
    });
  });

  it('リクエストが空なら成功で空配列を返す', async () => {
    const result = await buildReservations([], createCatalogLoader());

    expect(result).toEqual({ kind: 'ok', value: [] });
  });

  it('在庫ちょうどの数量なら成功する', async () => {
    const result = await buildReservations(
      [{ productId: 3, quantityInput: '3' }],
      createCatalogLoader()
    );

    expect(result.kind).toBe('ok');
  });
});

describe('buildReservations（失敗系）', () => {
  it('失敗は打ち切らずに集められる', async () => {
    const result = await buildReservations(
      [
        { productId: 1, quantityInput: '2' }, // 成功
        { productId: 4, quantityInput: '1' }, // 在庫0
        { productId: 99, quantityInput: '1' }, // 商品が無い
        { productId: 3, quantityInput: '0' }, // 数量が範囲外
      ],
      createCatalogLoader()
    );

    expect(result.kind).toBe('error');
    if (result.kind === 'error') {
      expect(result.error.map((error) => error.kind)).toEqual([
        'out_of_stock',
        'product_not_found',
        'quantity_out_of_range',
      ]);
      expect(result.error.map((error) => describeShopError(error))).toContain(
        'リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）'
      );
    }
  });

  it('在庫を差し替えれば在庫切れを自由に再現できる', async () => {
    const result = await buildReservations(
      [{ productId: 1, quantityInput: '2' }],
      createCatalogLoader(withStock(1, 1))
    );

    expect(result).toEqual({
      kind: 'error',
      error: [
        {
          kind: 'out_of_stock',
          productName: 'ラベンダーの石けん',
          requested: 2,
          available: 1,
        },
      ],
    });
  });

  it('カタログの読み込みが失敗したら、その1件だけを返す', async () => {
    const loader = vi.fn(createFailingLoader('fixture が見つかりません'));

    const result = await buildReservations([{ productId: 1, quantityInput: '1' }], loader);

    // 読み込みで打ち切るので、明細の処理には進まない
    expect(loader).toHaveBeenCalledTimes(1);
    expect(result).toEqual({
      kind: 'error',
      error: [{ kind: 'catalog_unavailable', reason: 'fixture が見つかりません' }],
    });
  });
});

describe('型のテスト', () => {
  it('buildReservations の戻り値は Result のユニオン', () => {
    expectTypeOf(buildReservations).returns.toEqualTypeOf<
      Promise<Result<Reservation[], ShopError[]>>
    >();
  });

  it('ShopError から在庫不足だけを取り出せる', () => {
    expectTypeOf<Extract<ShopError, { kind: 'out_of_stock' }>>().toEqualTypeOf<{
      kind: 'out_of_stock';
      productName: string;
      requested: number;
      available: number;
    }>();
  });

  it('loader の型は「カタログを返す非同期関数」', () => {
    expectTypeOf(createCatalogLoader).returns.toEqualTypeOf<() => Promise<CatalogItem[]>>();
  });
});
