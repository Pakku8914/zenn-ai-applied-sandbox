import { describe, expect, it } from 'vitest';
import { computeWindow } from '../windowing';
import { buildOffsets, computeVariableWindow } from './variableWindow';

describe('computeVariableWindow', () => {
  it('全行 40px なら、固定の行の高さ版（computeWindow）とすべての位置で一致する', () => {
    const offsets = buildOffsets(Array.from({ length: 2000 }, () => 40));
    for (let scrollTop = -100; scrollTop <= 80_100; scrollTop += 13) {
      expect(computeVariableWindow(offsets, 400, scrollTop, 5)).toEqual(
        computeWindow({ itemCount: 2000, rowHeight: 40, viewportHeight: 400, scrollTop, overscan: 5 }),
      );
    }
  });

  it('高さ [100, 50, 50, 200, 100]・表示枠 120px・120px の位置では 1〜3 行目を描く', () => {
    const offsets = buildOffsets([100, 50, 50, 200, 100]);
    expect(offsets).toEqual([0, 100, 150, 200, 400, 500]);
    expect(computeVariableWindow(offsets, 120, 120, 0)).toEqual({
      start: 1,
      end: 4,
      paddingTop: 100,
      paddingBottom: 100,
      totalHeight: 500,
    });
  });

  it('0 件なら空の範囲を返す', () => {
    expect(computeVariableWindow(buildOffsets([]), 400, 0, 5)).toEqual({
      start: 0,
      end: 0,
      paddingTop: 0,
      paddingBottom: 0,
      totalHeight: 0,
    });
  });
});
