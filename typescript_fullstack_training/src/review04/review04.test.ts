// 復習04 の問題6（テストの配分と CI の順序の診断）のテスト。
// vitest のグローバルは無効なので、describe / it / expect は必ず import する。
// 実行: docker compose exec ts npx vitest run src/review04
import { describe, expect, it } from 'vitest';
import {
  checkStepOrder,
  describeJudgement,
  estimateSuiteMs,
  findMissingSteps,
  judgeTestBalance,
  proposeRebalance,
  speedupRatio,
  toSeconds,
  totalTestCount,
} from './solutions';
import type { BalanceJudgement, StepId, TestCounts } from './solutions';

const CONE: TestCounts = { unit: 10, integration: 20, e2e: 70 };
const PYRAMID: TestCounts = { unit: 70, integration: 20, e2e: 10 };

const balanceCases: {
  label: string;
  counts: TestCounts;
  expected: BalanceJudgement['kind'];
}[] = [
  { label: 'ピラミッド型', counts: PYRAMID, expected: 'healthy' },
  { label: 'コーン型', counts: CONE, expected: 'ice-cream-cone' },
  { label: 'E2E が11%', counts: { unit: 70, integration: 19, e2e: 11 }, expected: 'ice-cream-cone' },
  { label: 'E2E ちょうど10%', counts: { unit: 80, integration: 10, e2e: 10 }, expected: 'healthy' },
  { label: 'ユニットちょうど60%', counts: { unit: 60, integration: 35, e2e: 5 }, expected: 'healthy' },
  { label: '統合テストばかり', counts: { unit: 30, integration: 60, e2e: 10 }, expected: 'unit-too-few' },
  { label: '1本も無い', counts: { unit: 0, integration: 0, e2e: 0 }, expected: 'empty' },
];

describe('問題6: テストの配分を診断する', () => {
  // 境界（E2E ちょうど10% / ユニットちょうど60%）を表として並べる
  it.each(balanceCases)('$label の判定は $expected', ({ counts, expected }) => {
    expect(judgeTestBalance(counts).kind).toBe(expected);
  });

  it('コーン型を提案どおりに直すと、同じ100本で6.3倍速くなる', () => {
    // Arrange: E2E に偏った100本
    const before = CONE;

    // Act
    const after = proposeRebalance(before);

    // Assert: 本数は変えず、配分だけを変える
    expect(after).toEqual({ unit: 70, integration: 20, e2e: 10 });
    expect(totalTestCount(after)).toBe(totalTestCount(before));
    expect(toSeconds(estimateSuiteMs(before))).toBe(570.1);
    expect(toSeconds(estimateSuiteMs(after))).toBe(90.7);
    expect(speedupRatio(before, after)).toBe(6.3);
    expect(describeJudgement(judgeTestBalance(after))).toBe('健全です（ユニット 70%）');
  });

  it('統合テストに偏っている場合も上限まで削る', () => {
    // Arrange & Act
    const after = proposeRebalance({ unit: 0, integration: 50, e2e: 50 });

    // Assert: 統合は30%、E2E は10%が上限。残りはユニットに回す
    expect(after).toEqual({ unit: 60, integration: 30, e2e: 10 });
    expect(judgeTestBalance(after).kind).toBe('healthy');
  });
});

describe('問題6: CI の順序を診断する', () => {
  const goodSteps: readonly StepId[] = [
    'checkout',
    'setup-node',
    'install',
    'typecheck',
    'lint',
    'test',
    'build',
  ];

  it('正しい順序なら指摘は出ない', () => {
    expect(checkStepOrder(goodSteps)).toEqual([]);
    expect(findMissingSteps(goodSteps)).toEqual([]);
  });

  it('ビルドがテストより前にあると2件指摘する', () => {
    // Arrange: 型チェックを最後に置き、テストの前にビルドしてしまった CI
    const steps: readonly StepId[] = [
      'checkout',
      'setup-node',
      'install',
      'build',
      'test',
      'lint',
      'typecheck',
    ];

    // Act & Assert
    expect(checkStepOrder(steps)).toEqual([
      'typecheck は test より前に置く',
      'test は build より前に置く',
    ]);
  });

  it('足りないステップを名前で挙げる', () => {
    expect(findMissingSteps(['checkout', 'setup-node', 'install', 'typecheck', 'test', 'build'])).toEqual(
      ['lint']
    );
  });
});
