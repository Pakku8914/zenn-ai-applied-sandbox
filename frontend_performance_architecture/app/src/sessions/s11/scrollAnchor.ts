/**
 * S11：スクロール位置を「ピクセル」ではなく「先頭に見えている商品の id ＋ずれ」で覚えて戻す。
 * 絞り込みや並び替えで行の並びが変わっても、同じ商品の位置へ戻れる。
 */
export type ScrollAnchor = {
  /** 表示枠の上端にかかっている商品の id */
  id: number;
  /** その行の上端から表示枠の上端までのずれ（px） */
  offset: number;
};

export function anchorAt(items: readonly { id: number }[], scrollTop: number, rowHeight: number): ScrollAnchor | null {
  const top = Math.max(0, scrollTop);
  const index = Math.floor(top / rowHeight);
  const item = items[index];
  if (item === undefined) {
    return null;
  }
  return { id: item.id, offset: top - index * rowHeight };
}

/** アンカーの商品がいまの一覧にあればその位置、無ければ先頭（0）を返す */
export function scrollTopFor(items: readonly { id: number }[], anchor: ScrollAnchor | null, rowHeight: number): number {
  if (anchor === null) {
    return 0;
  }
  const index = items.findIndex((item) => item.id === anchor.id);
  return index === -1 ? 0 : index * rowHeight + anchor.offset;
}
