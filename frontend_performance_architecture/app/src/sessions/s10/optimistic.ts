export type Favorites = ReadonlySet<number>;

/** お気に入りの集合を、元を書き換えずに更新する */
export function withFavorite(current: Favorites, id: number, on: boolean): Favorites {
  const next = new Set(current);
  if (on) next.add(id);
  else next.delete(id);
  return next;
}

/**
 * 失敗した操作だけを取り消す。
 * 送信後に利用者が同じ商品をもう一度押していたら（いまの値が attempted と違ったら）、
 * その新しい操作を優先して何もしない。送信前の集合を丸ごと戻すと、他の商品の操作まで消える。
 */
export function rollbackFavorite(current: Favorites, id: number, attempted: boolean): Favorites {
  return current.has(id) === attempted ? withFavorite(current, id, !attempted) : current;
}
