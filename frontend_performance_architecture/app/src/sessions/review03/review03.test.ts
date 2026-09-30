import { describe, expect, it } from 'vitest';
import { products } from '../../data/products';
import { CATEGORY_ALL, filterProducts } from '../s09/catalogQuery';
import { makeProducts } from '../s08/makeProducts';
import { anchorAt, scrollTopFor } from '../s11/scrollAnchor';
import { computeWindow } from '../s11/windowing';
import { chooseDesign, type ScreenRequirements } from './chooseDesign';
import { labelOf, traceHistory, type CatalogOp } from './historyTrace';
import { traceShown, type FetchCall } from './raceTrace';

describe('問題3：履歴の積み方（S09）', () => {
  const ops: CatalogOp[] = [
    { kind: 'typing', keyword: '商' },
    { kind: 'typing', keyword: '商品' },
    { kind: 'typing', keyword: '商品1' },
    { kind: 'commit', category: '文具' },
    { kind: 'typing', keyword: '商品12' },
    { kind: 'blur' },
    { kind: 'typing', keyword: '商品123' },
  ];

  it('7回の操作で履歴は5件（戻る4回で最初の画面）', () => {
    expect(traceHistory(ops).map(labelOf)).toEqual([
      '（空）｜すべて',
      '商品1｜すべて',
      '商品1｜文具',
      '商品12｜文具',
      '商品123｜文具',
    ]);
  });

  it('同じカテゴリを選び直しても履歴は増えない', () => {
    expect(traceHistory([...ops, { kind: 'commit', category: '文具' }])).toHaveLength(5);
  });
});

describe('問題3：競合状態（S10）', () => {
  // 練習用の架空の時間
  const calls: FetchCall[] = [
    { keyword: '商', startMs: 0, durationMs: 900 },
    { keyword: '商品', startMs: 100, durationMs: 150 },
    { keyword: '商品1', startMs: 200, durationMs: 100 },
  ];

  it('対策なしでは、最後に届いた「商」の結果が残る', () => {
    expect(traceShown(calls, false)).toEqual([
      { atMs: 250, keyword: '商品' },
      { atMs: 300, keyword: '商品1' },
      { atMs: 900, keyword: '商' },
    ]);
  });

  it('リクエスト ID で最新だけを採用すると「商品1」だけが表示される', () => {
    expect(traceShown(calls, true)).toEqual([{ atMs: 300, keyword: '商品1' }]);
  });

  it('件数：「商」は 2,000 件、「商品1」は 1,111 件', () => {
    const count = (keyword: string) => filterProducts(products, { keyword, category: CATEGORY_ALL }).length;
    expect(count('商')).toBe(2000);
    expect(count('商品1')).toBe(1111);
  });
});

describe('問題6：DOM に置く行の数（S11）', () => {
  const base = { rowHeight: 40, viewportHeight: 400, overscan: 5 };
  const rows = (itemCount: number, scrollTop: number) => {
    const r = computeWindow({ ...base, itemCount, scrollTop });
    return r.end - r.start;
  };

  it('2,000 件と 20,000 件で、同じ位置なら li の数は同じ', () => {
    expect([0, 4000, 4020, 1e9].map((top) => rows(2000, top))).toEqual([15, 20, 21, 15]);
    expect([0, 4000, 4020, 1e9].map((top) => rows(20_000, top))).toEqual([15, 20, 21, 15]);
  });

  it('スクロールバーの長さ（全体の高さ）は件数に比例する', () => {
    expect(computeWindow({ ...base, itemCount: 20_000, scrollTop: 0 }).totalHeight).toBe(800_000);
  });
});

describe('問題7：絞り込み後のスクロール位置（S11）', () => {
  const all = makeProducts(2000);
  const filtered = all.filter((p) => p.name.includes('商品1'));

  it('4,020px を維持すると先頭は商品189、アンカーで戻すと商品101（500px）', () => {
    expect(anchorAt(filtered, 4020, 40)).toEqual({ id: 189, offset: 20 });
    expect(scrollTopFor(filtered, anchorAt(all, 4020, 40), 40)).toBe(500);
  });
});

describe('問題8：chooseDesign（S09〜S12）', () => {
  const screens: Record<'A' | 'B' | 'C' | 'D', ScreenRequirements> = {
    // 公開の商品一覧：URL を SNS で共有される・検索流入が大事・2,000 件
    A: { shareableUrl: true, publicFirstView: true, itemCount: 2000, dataChangesOften: false, pageFindRequired: false },
    // ヘルプの「よくある質問」：50 件・ほとんど変わらない・Ctrl+F で探す
    B: { shareableUrl: false, publicFirstView: true, itemCount: 50, dataChangesOften: false, pageFindRequired: true },
    // ログイン後の在庫管理：20,000 件・在庫数が頻繁に変わる・条件付き URL を同僚に送る
    C: { shareableUrl: true, publicFirstView: false, itemCount: 20_000, dataChangesOften: true, pageFindRequired: false },
    // ログイン後の注文履歴：20,000 件・Ctrl+F で注文番号を探したい
    D: { shareableUrl: false, publicFirstView: false, itemCount: 20_000, dataChangesOften: false, pageFindRequired: true },
  };

  it('4つの画面の設計', () => {
    expect(chooseDesign(screens.A)).toEqual({ filterState: 'url', rendering: 'SSR', fetching: 'server', list: 'all' });
    expect(chooseDesign(screens.B)).toEqual({ filterState: 'local', rendering: 'ISR', fetching: 'server', list: 'all' });
    expect(chooseDesign(screens.C)).toEqual({
      filterState: 'url',
      rendering: 'SPA',
      fetching: 'client-swr',
      list: 'virtual',
    });
    expect(chooseDesign(screens.D)).toEqual({
      filterState: 'local',
      rendering: 'SPA',
      fetching: 'client-swr',
      list: 'paging',
    });
  });

  it('全件描画の境界は 2,000 件（2,001 件から全件描画をやめる）', () => {
    expect(chooseDesign({ ...screens.A, itemCount: 2001 }).list).toBe('virtual');
  });

  it('件数が負や小数なら RangeError', () => {
    expect(() => chooseDesign({ ...screens.A, itemCount: -1 })).toThrow(RangeError);
    expect(() => chooseDesign({ ...screens.A, itemCount: 1.5 })).toThrow(RangeError);
  });
});
