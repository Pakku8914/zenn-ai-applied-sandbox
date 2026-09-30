import { CONDITIONS, median, withPage } from '../vitals-client.ts';
import { INP_REPORT_THRESHOLD_MS, clickAndCollect, ms, type ClickRun } from './click-inp.ts';

/**
 * S07：「グラフを表示」のクリック INP を、出発点・タスク分割版・Web Worker 版で3回ずつ計測して比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session07/verify-inp.ts
 * 時間は大小関係と比率で、点列は完全一致で判定する。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const RUNS = 3;
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

type Summary = { inp: number; unreported: number; longestFrame: number; readyMs: number; chunks: number | null; runs: ClickRun[] };

async function measurePage(page: string): Promise<Summary> {
  const runs: ClickRun[] = [];
  for (let i = 0; i < RUNS; i += 1) {
    runs.push(await withPage((p) => clickAndCollect(p, `${TARGET}/pages/${page}/`)));
  }
  // 40ms 未満で報告されなかった回は、上限の 40ms として数える（改善版に有利にならない側に倒す）
  const inp = median(runs.map((r) => r.inp ?? INP_REPORT_THRESHOLD_MS));
  const longestFrame = median(runs.map((r) => Math.max(0, ...r.frames.map((f) => f.duration))));
  const readyMs = median(runs.map((r) => r.readyMs));
  const chunkRuns = runs.map((r) => r.chunks).filter((c): c is number => c !== null);
  const chunks = chunkRuns.length > 0 ? median(chunkRuns) : null;
  const unreported = runs.filter((r) => r.inp === null).length;

  console.log(
    `${page.padEnd(13)}: クリック INP ${ms(inp)}${unreported > 0 ? `（${unreported}回は40ms未満で未報告）` : ''}` +
      ` / 最長フレーム ${ms(longestFrame)} / 完成まで ${ms(readyMs)}${chunks === null ? '' : ` / 分割数 ${chunks}`}`,
  );
  return { inp, unreported, longestFrame, readyMs, chunks, runs };
}

const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各${RUNS}回の中央値）`,
);

const baseline = await measurePage('s07-baseline');
const chunked = await measurePage('s07-chunked');
const worker = await measurePage('s07-worker');
console.log('');

check('出発点のクリック INP が 200ms 以上（good の境界を超えている）', baseline.inp >= 200, ms(baseline.inp));
check('出発点では毎回 INP が報告されている', baseline.unreported === 0);
for (const [label, s] of [['タスク分割版', chunked], ['Web Worker 版', worker]] as const) {
  const ratio = s.inp / baseline.inp;
  check(`${label}のクリック INP 中央値が出発点の 0.5 倍以下`, ratio <= 0.5, `${ratio.toFixed(2)} 倍`);
  const frameRatio = s.longestFrame / baseline.longestFrame;
  check(`${label}のクリック後の最長フレームが出発点の 0.5 倍以下`, frameRatio <= 0.5, `${frameRatio.toFixed(2)} 倍`);
  const allStates = s.runs.every((r) => r.states[0] === 'pending' && r.states.at(-1) === 'ready');
  check(`${label}は「計算中」を先に描いてから完成形に切り替わる`, allStates, s.runs[0]?.states.join(' → ') ?? '');
}
check('タスク分割版は 2 スライス以上に分かれている', (chunked.chunks ?? 0) >= 2, `${chunked.chunks ?? 'なし'} スライス`);

// 点列は時間と無関係に決まるので完全一致で判定する
const reference = baseline.runs[0]?.polyline ?? '';
check('出発点の点列が 100 点ある', reference.split(' ').length === 100, `${reference.split(' ').length} 点`);
const allRuns = [...baseline.runs, ...chunked.runs, ...worker.runs];
const mismatched = allRuns.filter((r) => r.polyline !== reference).length;
check('3 ページ × 3 回すべての点列が出発点と完全に一致する', mismatched === 0, `不一致 ${mismatched} 件`);

console.log('\nクリックの内訳（出発点・1回目。Event Timing API の値）:');
const b = baseline.runs[0]?.breakdown;
console.log(
  b ? `入力遅延 ${ms(b.inputDelay)} / 処理時間 ${ms(b.processing)} / 表示遅延 ${ms(b.presentation)}` : '記録なし',
);
const worst = [...(baseline.runs[0]?.frames ?? [])].sort((x, y) => y.duration - x.duration)[0];
if (worst) {
  console.log(`出発点の最長フレーム: ${worst.type} ${ms(worst.duration)}（呼び出し元: ${worst.invokers.join(', ') || '不明'}）`);
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS07 のクリック INP 比較の検証に成功しました。');
