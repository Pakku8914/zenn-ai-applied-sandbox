/**
 * 横断復習③ 問題8：画面の要件から、状態・取得・描画・レンダリングの方式を選ぶ純粋関数。
 * メモ化の有無は出力しない。要件からは決まらず、計測してから決めるものだから（S08）。
 */
export type ScreenRequirements = {
  /** URL を送った相手や「戻る」操作で、同じ絞り込み結果を再現したい */
  shareableUrl: boolean;
  /** 初回訪問者や検索エンジンに、最初の表示の中身を早く見せたい */
  publicFirstView: boolean;
  /** 一覧の最大件数 */
  itemCount: number;
  /** データが頻繁に変わる（在庫数など、古い値を見せると困る） */
  dataChangesOften: boolean;
  /** ブラウザのページ内検索で、全件から探せる必要がある */
  pageFindRequired: boolean;
};

export type Design = {
  /** 絞り込み条件の置き場所（S09） */
  filterState: 'url' | 'local';
  /** HTML をいつ・どこで作るか（S12） */
  rendering: 'SPA' | 'SSR' | 'ISR';
  /** データをどこで取るか（S10・S12） */
  fetching: 'client-swr' | 'server';
  /** 一覧の描き方（S11） */
  list: 'all' | 'virtual' | 'paging';
};

/** 全件描画で良い上限。出発点の 2,000 件は入力の INP が good 域だった（S03・S08） */
export const RENDER_ALL_LIMIT = 2_000;

export function chooseDesign(req: ScreenRequirements): Design {
  if (!Number.isInteger(req.itemCount) || req.itemCount < 0) {
    throw new RangeError(`itemCount は 0 以上の整数にしてください: ${req.itemCount}`);
  }
  const filterState = req.shareableUrl ? 'url' : 'local';

  // 検索条件を URL（searchParams）から読むページはリクエストごとに描画される（動的レンダリング）
  const rendering = !req.publicFirstView
    ? 'SPA'
    : req.dataChangesOften || req.shareableUrl
      ? 'SSR'
      : 'ISR';

  const fetching = rendering === 'SPA' ? 'client-swr' : 'server';

  // 仮想化は見えていない行を DOM から外すので、ページ内検索では見つからなくなる
  const list =
    req.itemCount <= RENDER_ALL_LIMIT ? 'all' : req.pageFindRequired ? 'paging' : 'virtual';

  return { filterState, rendering, fetching, list };
}
