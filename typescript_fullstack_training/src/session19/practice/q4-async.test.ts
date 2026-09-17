// 問題4の解答：非同期処理と失敗のテスト。
import { describe, expect, it } from 'vitest';
import { delay } from '../../session17/async-tools';
import {
  formatCatalogItem,
  loadCatalog,
  loadProducts,
  readProductPages,
  reserveStockStub,
} from '../../session17/catalog';
import { requireById } from '../test-data';

/** 必ず失敗する非同期処理（失敗系のテスト用） */
async function loadBrokenCatalog(): Promise<string> {
  await delay(1);
  throw new Error('カタログの取得に失敗しました');
}

describe('loadCatalog', () => {
  it('カテゴリ名を紐づけたカタログを5件返す', async () => {
    const catalog = await loadCatalog();

    expect(catalog).toHaveLength(5);
    expect(formatCatalogItem(requireById(catalog, 1, 'カタログ項目'))).toBe(
      'ラベンダーの石けん（バス・ボディケア）480円 / 在庫24点'
    );
  });

  it('在庫0の商品は「在庫切れ」と表示される', async () => {
    const catalog = await loadCatalog();

    expect(formatCatalogItem(requireById(catalog, 4, 'カタログ項目'))).toBe(
      'リネンのふきん（ファブリック）990円 / 在庫切れ'
    );
  });
});

describe('readProductPages', () => {
  it('2件ずつ3ページに分けて読み出す', async () => {
    const pageSizes: number[] = [];

    for await (const products of readProductPages(2)) {
      pageSizes.push(products.length);
    }

    expect(pageSizes).toEqual([2, 2, 1]);
  });
});

describe('失敗するときのテスト', () => {
  it('rejects でエラーメッセージを確かめる', async () => {
    await expect(loadBrokenCatalog()).rejects.toThrow('カタログの取得に失敗しました');
  });

  it('在庫0の商品は確保に失敗する', async () => {
    const products = await loadProducts();
    const linen = requireById(products, 4, '商品');

    await expect(reserveStockStub(linen)).rejects.toThrow('在庫がありません');
  });
});
