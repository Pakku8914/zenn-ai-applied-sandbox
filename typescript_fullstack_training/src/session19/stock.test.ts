// 例外を投げる版と Result を返す版のテスト。本文5節に対応する。
import { describe, expect, it } from 'vitest';
import { describeShopError, parseQuantity, reserveStock } from '../session18/shop';
import { StockShortageError, reserveStockOrThrow } from './stock';
import { requireCatalogItem } from './test-data';

describe('reserveStockOrThrow（例外を投げる版）', () => {
  it('在庫が足りていれば明細を返す', () => {
    // Arrange: マグカップ（2350円・在庫3点）
    const mug = requireCatalogItem(3);

    // Act
    const reservation = reserveStockOrThrow(mug, 2);

    // Assert
    expect(reservation).toEqual({
      productId: 3,
      productName: 'マグカップ',
      quantity: 2,
      lineTotal: 4700,
    });
  });

  it('在庫ちょうどの数量なら成功する', () => {
    expect(reserveStockOrThrow(requireCatalogItem(3), 3).lineTotal).toBe(7050);
  });

  it('在庫が足りなければ StockShortageError を投げる', () => {
    const linen = requireCatalogItem(4); // リネンのふきん（在庫0）

    // 関数呼び出しを () => で包む。包まないとテスト自体がエラーで終わってしまう
    expect(() => reserveStockOrThrow(linen, 1)).toThrow(StockShortageError);
    expect(() => reserveStockOrThrow(linen, 1)).toThrow(
      'リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）'
    );
  });

  it('数量が0以下なら呼び出し側のバグとして RangeError を投げる', () => {
    expect(() => reserveStockOrThrow(requireCatalogItem(1), 0)).toThrow(RangeError);
  });
});

describe('reserveStock（Result を返す版）', () => {
  it('成功なら kind が ok になり、明細を値として読める', () => {
    const result = reserveStock(requireCatalogItem(3), 2);

    expect(result.kind).toBe('ok');
    // kind で絞り込んでから value を読む（型の絞り込みがテストでもそのまま効く）
    if (result.kind === 'ok') {
      expect(result.value.lineTotal).toBe(4700);
    }
  });

  it('在庫不足なら失敗を丸ごと比較できる', () => {
    expect(reserveStock(requireCatalogItem(4), 2)).toEqual({
      kind: 'error',
      error: {
        kind: 'out_of_stock',
        productName: 'リネンのふきん',
        requested: 2,
        available: 0,
      },
    });
  });

  it('失敗しても例外は飛ばないので、複数まとめて判定できる', () => {
    const results = [requireCatalogItem(3), requireCatalogItem(4)].map((item) =>
      reserveStock(item, 1)
    );

    expect(results.map((result) => result.kind)).toEqual(['ok', 'error']);
  });
});

describe('parseQuantity の境界', () => {
  const cases: { input: string; expected: 'ok' | 'error' }[] = [
    { input: '0', expected: 'error' },
    { input: '1', expected: 'ok' },
    { input: '10', expected: 'ok' },
    { input: '11', expected: 'error' },
    { input: '1.5', expected: 'error' },
    { input: '', expected: 'error' },
  ];

  it.each(cases)('入力 "$input" → $expected', ({ input, expected }) => {
    expect(parseQuantity(input).kind).toBe(expected);
  });

  it('失敗の理由が利用者向けの1文になる', () => {
    const result = parseQuantity('abc');

    expect(result.kind).toBe('error');
    if (result.kind === 'error') {
      expect(describeShopError(result.error)).toBe(
        '数量は整数で入力してください（受け取った値: abc）'
      );
    }
  });
});
