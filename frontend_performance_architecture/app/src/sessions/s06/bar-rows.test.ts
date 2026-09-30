import { describe, expect, it } from 'vitest';
import { summarize } from './animate';
import { barWidthPx } from './bar-rows';

describe('barWidthPx', () => {
  it('価格の最大値（9,999 円）では枠の幅いっぱいになる', () => {
    expect(barWidthPx(500, 9_999)).toBe(500);
  });
  it('価格の最小値（100 円）では枠の 1% になる', () => {
    expect(barWidthPx(500, 100)).toBe(5);
  });
});

describe('summarize', () => {
  it('フレーム間隔の平均と、予算の 1.5 倍を超えた回数を数える', () => {
    // 16.7ms 間隔が 3 回、50ms 間隔が 1 回
    expect(summarize([0, 16.7, 33.4, 50.1, 100.1])).toEqual({
      frames: 5,
      averageIntervalMs: 100.1 / 4,
      slowFrames: 1,
    });
  });
});
