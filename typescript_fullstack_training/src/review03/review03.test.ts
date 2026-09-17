// 復習03 の問題2・問題6・問題7 の解答（テスト）。
// vitest のグローバルは無効なので、describe / it / expect / vi は必ず import する。
// 実行: docker compose exec ts npx vitest run src/review03
import { describe, expect, it, vi } from 'vitest';
import { findProductById, isWithinQuantityLimit } from '../session16/cart';
import { buildPaymentSummary, calcShippingFee, resolveDiscountRule } from '../session16/pricing';
import type { CartLine } from '../session16/types';
import { createSlowThenFastTask } from '../session17/async-tools';
import { loadJsonText, reserveStockStub } from '../session17/catalog';
import type { Product } from '../session17/catalog';
import { loadProductReport, loadWithRetry } from './solutions';

/** 商品マスタから明細を1行作る（テストの Arrange を短く書くための道具） */
function line(productId: number, quantity: number): CartLine {
  const product = findProductById(productId);
  if (product === undefined) {
    throw new Error(`商品マスタが壊れています: id=${productId}`);
  }
  return { product, quantity };
}

/** 在庫切れの商品（fixtures の4番目と同じ値） */
const LINEN_CLOTH: Product = {
  id: 4,
  name: 'リネンのふきん',
  price: 990,
  stock: 0,
  description: '洗うほどやわらかくなるリネン100%のふきんです。',
  imageUrl: '/images/products/linen-cloth.png',
  categoryId: 3,
};

describe('問題2: 送料と数量の境界値', () => {
  // 3000円ちょうどが無料になる境界。テーブル駆動で「表」として並べる
  it.each([
    { totalWithTax: 0, expected: 500 },
    { totalWithTax: 2999, expected: 500 },
    { totalWithTax: 3000, expected: 0 },
    { totalWithTax: 3001, expected: 0 },
  ])('税込商品合計 $totalWithTax 円の送料は $expected 円', ({ totalWithTax, expected }) => {
    expect(calcShippingFee(totalWithTax)).toBe(expected);
  });

  it.each([
    { quantity: 0, expected: false },
    { quantity: 1, expected: true },
    { quantity: 10, expected: true },
    { quantity: 11, expected: false },
  ])('数量 $quantity は範囲内か → $expected', ({ quantity, expected }) => {
    expect(isWithinQuantityLimit(line(1, quantity))).toBe(expected);
  });

  it('税抜2400円は税込2640円なので送料がかかる', () => {
    // Arrange: ラベンダーの石けん（480円）×5点
    const lines = [line(1, 5)];

    // Act
    const summary = buildPaymentSummary(lines, resolveDiscountRule('none'));

    // Assert: 税抜では3000円未満、税込でも3000円未満
    expect(summary.subtotal).toBe(2400);
    expect(summary.totalWithTax).toBe(2640);
    expect(summary.shippingFee).toBe(500);
    expect(summary.payableAmount).toBe(3140);
  });

  it('税抜2760円は税込3036円なので送料は無料になる', () => {
    // Arrange: 石けん×2点 + ハンドクリーム×1点
    const lines = [line(1, 2), line(2, 1)];

    // Act
    const summary = buildPaymentSummary(lines, resolveDiscountRule('none'));

    // Assert: 税抜は3000円未満だが、税込で3000円を超えるので無料
    expect(summary.subtotal).toBe(2760);
    expect(summary.totalWithTax).toBe(3036);
    expect(summary.shippingFee).toBe(0);
    expect(summary.payableAmount).toBe(3036);
  });

  it('割引で税込が3000円を下回ると送料がかかり、支払総額が高くなる', () => {
    // Arrange: マグカップ×1点 + 石けん×1点（税抜2830円）
    const lines = [line(3, 1), line(1, 1)];

    // Act
    const none = buildPaymentSummary(lines, resolveDiscountRule('none'));
    const gold = buildPaymentSummary(lines, resolveDiscountRule('gold'));

    // Assert: 10%割引で税込2801円になり、送料500円が復活する
    expect(none.payableAmount).toBe(3113);
    expect(gold.discountAmount).toBe(283);
    expect(gold.totalWithTax).toBe(2801);
    expect(gold.shippingFee).toBe(500);
    expect(gold.payableAmount).toBe(3301);
    expect(gold.payableAmount).toBeGreaterThan(none.payableAmount);
  });
});

describe('問題6: タイムアウトとリトライ', () => {
  it('2回タイムアウトしてから3回目で成功する', async () => {
    // Arrange: 2回目までは 200ms、3回目以降は 5ms で終わる処理
    const task = createSlowThenFastTask();
    const waits: string[] = [];
    const onRetry = vi.fn((attempt: number, waitMs: number) => {
      waits.push(`${attempt}回目の失敗 → ${waitMs}ms 待つ`);
    });

    // Act: 制限時間 30ms・追加2回・初回の待ち 1ms
    const result = await loadWithRetry(task, { timeoutMs: 30, retries: 2, baseMs: 1 }, onRetry);

    // Assert: 偽のタイマーを使わなくても 100ms 以内に終わる
    expect(result).toEqual({ kind: 'ok', value: '成功（3回目・5ms）' });
    expect(onRetry).toHaveBeenCalledTimes(2);
    expect(waits).toEqual(['1回目の失敗 → 1ms 待つ', '2回目の失敗 → 2ms 待つ']);
  });

  it('リトライしない設定では制限時間を超えて失敗する', async () => {
    // Arrange
    const task = createSlowThenFastTask();

    // Act
    const result = await loadWithRetry(task, { timeoutMs: 20, retries: 0, baseMs: 1 });

    // Assert: 失敗も戻り値なので、try / catch なしで中身を確かめられる
    expect(result).toEqual({ kind: 'error', error: '制限時間 20ms を超えました' });
  });

  it('在庫切れの商品を確保しようとすると例外が飛ぶ', async () => {
    // 例外を投げる関数のテストは rejects を挟む（await の位置を間違えやすい）
    await expect(reserveStockStub(LINEN_CLOTH)).rejects.toThrow('在庫がありません');
  });
});

describe('問題7: レポートの組み立て', () => {
  it('fixtures の5件からカテゴリ別のレポートを作る', async () => {
    // Act: 既定の読み込み係（fixtures を読む）を使う
    const report = await loadProductReport({ timeoutMs: 500, retries: 1, baseMs: 5 });

    // Assert: 1行ずつ比べれば、どこが崩れたかがすぐ分かる
    expect(report).toEqual({
      kind: 'ok',
      value: [
        '=== 商品カタログ レポート ===',
        'バス・ボディケア: 2件 / 在庫金額 33120円',
        'キッチン雑貨: 1件 / 在庫金額 7050円',
        'ファブリック: 2件 / 在庫金額 14000円',
        '在庫切れ: リネンのふきん',
        '合計: 5件 / 54170円',
      ],
    });
  });

  it('読み込みに失敗しても例外ではなく Result で返る', async () => {
    // Arrange: products.json だけ読めない読み込み係を渡す（依存を引数で渡す設計なのでモック不要）
    const failingRead = async (fileName: string): Promise<string> => {
      if (fileName === 'products.json') {
        throw new Error('ネットワークに接続できません');
      }
      return loadJsonText(fileName);
    };

    // Act
    const report = await loadProductReport({ timeoutMs: 200, retries: 0, baseMs: 1 }, failingRead);

    // Assert
    expect(report.kind).toBe('error');
    if (report.kind === 'error') {
      expect(report.error).toContain('products.json を読み込めません');
    }
  });
});
