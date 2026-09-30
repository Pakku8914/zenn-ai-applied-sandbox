import { median, withPage } from '../vitals-client.ts';
import { conditionsLabel, createChecker, ms1, openLab } from './lab.ts';

/**
 * S06：カートパネルを開くアニメーションを 1 秒ずつ動かし、requestAnimationFrame が何回呼ばれたか
 * （何フレーム描けたか）で比べる。
 *   width     … Bad。一覧の幅を毎フレーム縮める
 *   transform … Good。パネルを重ねて transform で滑り込ませる
 *   settle    … 練習問題7の解答。動く間は transform だけ、一覧の幅は最後に1回だけ変える
 * 実行: docker compose exec measure node --experimental-strip-types src/session06/verify-animation.ts
 */
const RUNS = 3;
const DURATION_MS = 1_000;
const KINDS = ['width', 'transform', 'settle'] as const;
const { check, finish } = createChecker();

type Report = { frames: number; averageIntervalMs: number; slowFrames: number };

const reports = await withPage(async (page) => {
  await openLab(page);
  const result: Record<(typeof KINDS)[number], Report[]> = { width: [], transform: [], settle: [] };
  // 3つの版を交互に動かし、時間の経過による揺れが1つの版に偏らないようにする
  for (let i = 0; i < RUNS; i += 1) {
    for (const kind of KINDS) {
      result[kind].push(await page.evaluate(([k, d]) => window.__s06Lab!.animate(k, d), [kind, DURATION_MS] as const));
    }
  }
  return result;
});

const summarize = (label: string, list: Report[]) => {
  const interval = median(list.map((r) => r.averageIntervalMs));
  return {
    row: {
      版: label,
      フレーム数: median(list.map((r) => r.frames)),
      平均フレーム間隔: ms1(interval),
      fps: Math.round(1000 / interval),
      落ちたフレーム: median(list.map((r) => r.slowFrames)),
    },
    interval,
  };
};
const bad = summarize('width（Bad）', reports.width);
const good = summarize('transform（Good）', reports.transform);
const settle = summarize('settle（問題7）', reports.settle);

console.log(`計測条件: ${conditionsLabel()} / ${DURATION_MS.toLocaleString('en-US')}ms のアニメーション / 各${RUNS}回の中央値`);
console.table([bad.row, good.row, settle.row]);

check(
  'すべての版でフレームが 10 回以上記録された',
  [bad, good, settle].every((s) => s.row.フレーム数 >= 10),
  [bad, good, settle].map((s) => s.row.フレーム数).join(' / '),
);
const ratio = good.interval / bad.interval;
check('transform 版の平均フレーム間隔が width 版の 0.7 倍以下', ratio <= 0.7, `${ratio.toFixed(2)} 倍`);
check('transform 版の落ちたフレームが width 版以下', good.row.落ちたフレーム <= bad.row.落ちたフレーム, `${good.row.落ちたフレーム} / ${bad.row.落ちたフレーム}`);
const settleRatio = settle.interval / bad.interval;
check('settle 版の平均フレーム間隔が width 版の 0.7 倍以下', settleRatio <= 0.7, `${settleRatio.toFixed(2)} 倍`);

finish('S06 のアニメーション');
