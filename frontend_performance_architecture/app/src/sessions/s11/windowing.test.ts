import { describe, expect, it } from 'vitest';
import { makeProducts } from '../s08/makeProducts';
import { anchorAt, scrollTopFor } from './scrollAnchor';
import { computeWindow, maxRenderedRows } from './windowing';

// 本章の一覧と同じ条件：行 40px・表示枠 400px（10 行分）・オーバースキャン 5 行
const base = { rowHeight: 40, viewportHeight: 400, overscan: 5 };

describe('computeWindow', () => {
  it('先頭では 0〜15 行目（見えている 10 行＋下のオーバースキャン 5 行）', () => {
    expect(computeWindow({ ...base, itemCount: 2000, scrollTop: 0 })).toEqual({
      start: 0,
      end: 15,
      paddingTop: 0,
      paddingBottom: 79_400,
      totalHeight: 80_000,
    });
  });

  it('4,000px では 95〜115 行目（上下にオーバースキャン 5 行ずつ）', () => {
    expect(computeWindow({ ...base, itemCount: 2000, scrollTop: 4000 })).toEqual({
      start: 95,
      end: 115,
      paddingTop: 3_800,
      paddingBottom: 75_400,
      totalHeight: 80_000,
    });
  });

  it('4,020px（行の途中で止まる）では下端の行が 1 行増えて 95〜116 行目', () => {
    expect(computeWindow({ ...base, itemCount: 2000, scrollTop: 4020 })).toEqual({
      start: 95,
      end: 116,
      paddingTop: 3_800,
      paddingBottom: 75_360,
      totalHeight: 80_000,
    });
  });

  it('末尾を超える値は末尾に、負の値は先頭に丸める', () => {
    expect(computeWindow({ ...base, itemCount: 2000, scrollTop: 1e9 })).toEqual({
      start: 1985,
      end: 2000,
      paddingTop: 79_400,
      paddingBottom: 0,
      totalHeight: 80_000,
    });
    expect(computeWindow({ ...base, itemCount: 2000, scrollTop: -50 })).toEqual(
      computeWindow({ ...base, itemCount: 2000, scrollTop: 0 }),
    );
  });

  it('0 件・表示枠より少ない件数でも破綻しない', () => {
    expect(computeWindow({ ...base, itemCount: 0, scrollTop: 0 })).toEqual({
      start: 0,
      end: 0,
      paddingTop: 0,
      paddingBottom: 0,
      totalHeight: 0,
    });
    expect(computeWindow({ ...base, itemCount: 3, scrollTop: 500 })).toEqual({
      start: 0,
      end: 3,
      paddingTop: 0,
      paddingBottom: 0,
      totalHeight: 120,
    });
  });

  it('20,000 件でも、同じ位置なら描く行の数は 2,000 件と同じ', () => {
    for (const scrollTop of [0, 4000, 4020]) {
      const small = computeWindow({ ...base, itemCount: 2000, scrollTop });
      const large = computeWindow({ ...base, itemCount: 20_000, scrollTop });
      expect(large.end - large.start).toBe(small.end - small.start);
    }
  });

  it('どの位置でも描く行は maxRenderedRows（21 行）以下で、高さの合計は全件分に一致する', () => {
    expect(maxRenderedRows(40, 400, 5)).toBe(21);
    for (let scrollTop = 0; scrollTop <= 80_000; scrollTop += 7) {
      const r = computeWindow({ ...base, itemCount: 2000, scrollTop });
      expect(r.end - r.start).toBeLessThanOrEqual(21);
      expect(r.paddingTop + (r.end - r.start) * 40 + r.paddingBottom).toBe(r.totalHeight);
    }
  });

  it('rowHeight が 0 以下なら RangeError', () => {
    expect(() => computeWindow({ ...base, rowHeight: 0, itemCount: 10, scrollTop: 0 })).toThrow(RangeError);
  });
});

describe('scrollAnchor', () => {
  const all = makeProducts(2000);
  // 「商品1」で絞り込むと 商品1・商品10〜19・商品100〜199・… の 1,111 件になる
  const filtered = all.filter((p) => p.name.includes('商品1'));

  it('4,020px は「商品101 の上端から 20px」として覚える', () => {
    expect(anchorAt(all, 4020, 40)).toEqual({ id: 101, offset: 20 });
  });

  it('絞り込み後は、商品101 の位置（13 行目 → 500px）へ戻す', () => {
    const anchor = anchorAt(all, 4020, 40);
    expect(scrollTopFor(all, anchor, 40)).toBe(4020);
    expect(scrollTopFor(filtered, anchor, 40)).toBe(500);
  });

  it('ピクセルのまま戻すと、絞り込み後は別の商品（商品189）が先頭に来てしまう', () => {
    expect(anchorAt(filtered, 4020, 40)).toEqual({ id: 189, offset: 20 });
  });

  it('アンカーの商品がいまの一覧に無ければ先頭（0）に戻す', () => {
    const withoutAnchor = all.filter((p) => p.name.includes('商品2'));
    expect(scrollTopFor(withoutAnchor, { id: 101, offset: 20 }, 40)).toBe(0);
    expect(scrollTopFor(all, null, 40)).toBe(0);
    expect(anchorAt([], 0, 40)).toBeNull();
  });
});
