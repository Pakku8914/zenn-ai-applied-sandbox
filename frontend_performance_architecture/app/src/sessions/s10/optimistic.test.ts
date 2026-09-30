import { describe, expect, it } from 'vitest';
import { rollbackFavorite, withFavorite } from './optimistic';

describe('楽観的更新のロールバック', () => {
  it('失敗した操作だけを取り消す（他の商品の操作は残る）', () => {
    // 商品1 を追加（成功）→ 商品3 を追加（失敗）
    let favorites = withFavorite(new Set(), 1, true);
    favorites = withFavorite(favorites, 3, true);
    favorites = rollbackFavorite(favorites, 3, true);
    expect([...favorites]).toEqual([1]);
  });

  it('送信後に同じ商品がもう一度押されていたら、新しい操作を優先して触らない', () => {
    // 商品3 を追加（送信中）→ 利用者がすぐ解除 → 最初の追加が失敗
    let favorites = withFavorite(new Set(), 3, true);
    favorites = withFavorite(favorites, 3, false);
    const after = rollbackFavorite(favorites, 3, true);
    expect(after.has(3)).toBe(false);
    expect(after).toBe(favorites); // 何もしないので同じ参照
  });

  it('元の集合は書き換えない', () => {
    const original = new Set([1]);
    withFavorite(original, 2, true);
    expect([...original]).toEqual([1]);
  });
});
