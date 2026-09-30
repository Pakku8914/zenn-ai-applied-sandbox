import { describe, expect, it } from 'vitest';
import { droppedFrames, fitsInFrame, frameBudgetMs, isLongTask } from './frameBudget';
import { trustIssues, type MeasurementReport } from './trustReport';

const BOOK_CONDITIONS = { cpuThrottlingRate: 4, downloadKbps: 1_500, latencyMs: 40 };

describe('frameBudget（問題1）', () => {
  it('リフレッシュレートごとの予算', () => {
    expect(frameBudgetMs(60).toFixed(1)).toBe('16.7');
    expect(frameBudgetMs(90).toFixed(1)).toBe('11.1');
    expect(frameBudgetMs(120).toFixed(1)).toBe('8.3');
  });

  it('クリック INP（264／248／328ms）の中央値 264ms で描けなかったフレーム', () => {
    expect(droppedFrames(264)).toBe(16);
    expect(droppedFrames(264, 120)).toBe(32);
    expect(droppedFrames(328)).toBe(20);
    // セッション2の「200ms 塞ぐと約 12 枚」と同じ数え方であること
    expect(droppedFrames(200)).toBe(12);
  });

  it('長いタスクの境界は 50ms 以上', () => {
    expect(isLongTask(264)).toBe(true);
    expect(isLongTask(50)).toBe(true);
    expect(isLongTask(49)).toBe(false);
  });

  it('処理 X（6 + 4 = 10ms）と処理 Y（3 + 9 = 12ms）', () => {
    expect([60, 90, 120].map((hz) => fitsInFrame(6 + 4, hz))).toEqual([true, true, false]);
    expect([60, 90, 120].map((hz) => fitsInFrame(3 + 9, hz))).toEqual([true, false, false]);
  });
});

describe('trustIssues（問題2・問題8）', () => {
  const reports: Record<'A' | 'B' | 'C' | 'D', MeasurementReport> = {
    A: { target: 'unknown', runs: 1, aggregate: 'single', comparison: { sameConditions: false } },
    B: { target: 'dev', conditions: BOOK_CONDITIONS, runs: 3, aggregate: 'mean' },
    C: { target: 'preview', conditions: BOOK_CONDITIONS, runs: 1, aggregate: 'single' },
    D: {
      target: 'preview',
      conditions: BOOK_CONDITIONS,
      runs: 3,
      aggregate: 'median',
      comparison: { sameConditions: true },
    },
  };

  it('報告 A は4つの問題を持つ', () => {
    expect(trustIssues(reports.A)).toEqual([
      '計測条件が書かれていない',
      '本番ビルドを計測したか分からない',
      '計測回数が 3 回未満',
      '改善前後を同じ条件で計測したと確認できない',
    ]);
  });

  it('報告 B は開発サーバーと平均', () => {
    expect(trustIssues(reports.B)).toEqual(['開発サーバーを計測している', '平均を代表値にしている']);
  });

  it('報告 C は1回だけ', () => {
    expect(trustIssues(reports.C)).toEqual(['計測回数が 3 回未満']);
  });

  it('報告 D は根拠として使える', () => {
    expect(trustIssues(reports.D)).toEqual([]);
  });
});
