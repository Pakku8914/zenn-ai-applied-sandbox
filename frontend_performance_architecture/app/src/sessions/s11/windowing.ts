/**
 * S11：固定の行の高さで、スクロール位置から「DOM に置く行の範囲」を計算する純粋関数。
 * DOM にも React にも触らないので、vitest（環境 node）で値を完全一致で固定できる。
 */
export type WindowInput = {
  /** 全体の行数（絞り込み後） */
  itemCount: number;
  /** 1 行の高さ（px）。全行で同じであることが前提 */
  rowHeight: number;
  /** 表示枠（スクロールするコンテナ）の高さ（px） */
  viewportHeight: number;
  /** 表示枠の scrollTop（px） */
  scrollTop: number;
  /** 見えている範囲の上下に余分に描く行数 */
  overscan: number;
};

export type WindowRange = {
  /** 描く最初の行の番号（0 始まり・含む） */
  start: number;
  /** 描く最後の行の次の番号（含まない） */
  end: number;
  /** 上のスペーサーの高さ（描かない行の分） */
  paddingTop: number;
  /** 下のスペーサーの高さ（描かない行の分） */
  paddingBottom: number;
  /** 全行を並べたときの高さ。スクロールバーの長さはこれで決まる */
  totalHeight: number;
};

export function computeWindow({ itemCount, rowHeight, viewportHeight, scrollTop, overscan }: WindowInput): WindowRange {
  if (!(rowHeight > 0)) {
    throw new RangeError(`rowHeight は正の数にしてください: ${rowHeight}`);
  }
  const totalHeight = itemCount * rowHeight;
  // 絞り込みで行が減った直後や、Mac の慣性スクロールで負になった値を端に丸める
  const maxScrollTop = Math.max(0, totalHeight - viewportHeight);
  const top = Math.min(Math.max(0, scrollTop), maxScrollTop);

  const firstVisible = Math.floor(top / rowHeight);
  const lastVisible = Math.min(itemCount, Math.ceil((top + viewportHeight) / rowHeight));

  const start = Math.max(0, firstVisible - overscan);
  const end = Math.min(itemCount, lastVisible + overscan);
  return {
    start,
    end,
    paddingTop: start * rowHeight,
    paddingBottom: (itemCount - end) * rowHeight,
    totalHeight,
  };
}

/** どのスクロール位置でも、DOM に置く行はこの数を超えない（行の途中で止まると 1 行増える） */
export function maxRenderedRows(rowHeight: number, viewportHeight: number, overscan: number): number {
  return Math.ceil(viewportHeight / rowHeight) + 1 + overscan * 2;
}
