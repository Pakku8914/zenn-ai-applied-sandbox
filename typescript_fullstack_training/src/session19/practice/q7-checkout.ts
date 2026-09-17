// 問題7：チェックアウト（在庫引当）のテストで使う loader スタブ。
//
// セッション18の buildReservations / loadCatalogSafely は
// カタログの読み込み関数を引数で受け取る設計なので、
// 成功・失敗・在庫の状態を自由に作れる。モジュールのモックは不要。

import { delay } from '../../session17/async-tools';
import type { CatalogItem } from '../../session17/catalog';
import { catalogItems } from '../test-data';

/** 渡したカタログをそのまま返す loader（既定は商品マスタ5件） */
export function createCatalogLoader(
  items: readonly CatalogItem[] = catalogItems
): () => Promise<CatalogItem[]> {
  return async () => {
    await delay(1); // 実際の読み込みにも時間がかかるので、非同期であることを保つ
    return [...items];
  };
}

/** 必ず失敗する loader（読み込みエラーの再現用） */
export function createFailingLoader(message: string): () => Promise<CatalogItem[]> {
  return async () => {
    await delay(1);
    throw new Error(message);
  };
}

/** 指定した商品の在庫だけを差し替えたカタログを作る（在庫切れの再現用） */
export function withStock(id: number, stock: number): readonly CatalogItem[] {
  return catalogItems.map((item) => (item.id === id ? { ...item, stock } : item));
}
