import { describe, expect, it } from 'vitest';
import { makeProducts } from '../../s08/makeProducts';
import { anchorAt, scrollTopFor } from '../scrollAnchor';
import { computeWindow } from '../windowing';

// 練習問題2：行 40px・表示枠 400px の条件で手計算した値を固定する
describe('問題2：computeWindow の手計算', () => {
  const at = (itemCount: number, scrollTop: number, overscan: number) =>
    computeWindow({ itemCount, rowHeight: 40, viewportHeight: 400, scrollTop, overscan });

  it('(a) 2,000 件・1,000px：見えている 25〜34 行目の上下に 5 行ずつ', () => {
    expect(at(2000, 1000, 5)).toEqual({ start: 20, end: 40, paddingTop: 800, paddingBottom: 78_400, totalHeight: 80_000 });
  });

  it('(b) 2,000 件・1,010px：行の途中なので見えている行が 11 行になり、1 行増える', () => {
    expect(at(2000, 1010, 5)).toEqual({ start: 20, end: 41, paddingTop: 800, paddingBottom: 78_360, totalHeight: 80_000 });
  });

  it('(c) 1,111 件・79,600px（絞り込み直後の古い値）：末尾の 44,040px に丸める', () => {
    expect(at(1111, 79_600, 5)).toEqual({ start: 1096, end: 1111, paddingTop: 43_840, paddingBottom: 0, totalHeight: 44_440 });
  });

  it('(d) 8 件・0px：全件が表示枠に収まる', () => {
    expect(at(8, 0, 5)).toEqual({ start: 0, end: 8, paddingTop: 0, paddingBottom: 0, totalHeight: 320 });
  });

  it('(e) 2,000 件・4,000px・オーバースキャン 0：見えている 10 行だけ', () => {
    expect(at(2000, 4000, 0)).toEqual({ start: 100, end: 110, paddingTop: 4_000, paddingBottom: 75_600, totalHeight: 80_000 });
  });
});

// 練習問題4：スクロール位置を商品 id で覚えて戻す
describe('問題4：スクロールアンカー', () => {
  const all = makeProducts(2000);
  // 「商品2」を含むのは 商品2・商品20〜29・商品200〜299・商品2000 の 112 件
  const withTwo = all.filter((p) => p.name.includes('商品2'));

  it('8,030px は「商品201 の上端から 30px」', () => {
    expect(withTwo).toHaveLength(112);
    expect(anchorAt(all, 8030, 40)).toEqual({ id: 201, offset: 30 });
  });

  it('「商品2」で絞り込んだ一覧では、商品201 は 13 行目なので 510px に戻す', () => {
    expect(scrollTopFor(withTwo, { id: 201, offset: 30 }, 40)).toBe(510);
  });

  it('ピクセルのまま当てはめると末尾を超え、丸められて商品291 が先頭に来る', () => {
    expect(anchorAt(withTwo, 8030, 40)).toBeNull();
    const range = computeWindow({ itemCount: withTwo.length, rowHeight: 40, viewportHeight: 400, scrollTop: 8030, overscan: 0 });
    expect(withTwo[range.start]?.id).toBe(291);
  });

  it('アンカーの商品が一覧に無ければ先頭（0）', () => {
    const withOne = all.filter((p) => p.name.includes('商品1'));
    expect(scrollTopFor(withOne, { id: 201, offset: 30 }, 40)).toBe(0);
  });
});
