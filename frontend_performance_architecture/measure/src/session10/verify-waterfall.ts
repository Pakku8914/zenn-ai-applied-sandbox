import { median, withPage } from '../vitals-client.ts';
import { createChecker, maxConcurrency, pageUrl, readCalls } from './helpers.ts';

/**
 * S10：直列取得（ウォーターフォール）を並列化すると、表示完了までの時間が縮むことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session10/verify-waterfall.ts
 * 呼び出し回数と並列度は決定的なので完全一致、時間は比率（Good が Bad の 0.6 倍以下）で判定する。
 */
const RUNS = 3;
const { check, finish } = createChecker();

type Run = { calls: number; concurrency: number; durationMs: number };

async function measureOnce(name: string): Promise<Run> {
  return withPage(async (page) => {
    await page.goto(pageUrl(name), { waitUntil: 'load' });
    // page.evaluate に渡す関数はブラウザ側で実行されるので、外側の関数を参照せずに書く
    const handle = await page.waitForFunction(
      () => (window as unknown as { __s10DoneAt?: number }).__s10DoneAt,
      undefined,
      { timeout: 15_000 },
    );
    const doneAt = (await handle.jsonValue()) as number;
    const calls = await readCalls(page);
    const firstStart = Math.min(...calls.map((c) => c.startedAt));
    // 最初の取得を始めてから、3つのデータがすべて画面に出るまで
    return { calls: calls.length, concurrency: maxConcurrency(calls), durationMs: doneAt - firstStart };
  });
}

async function measureRuns(name: string): Promise<Run[]> {
  const runs: Run[] = [];
  for (let i = 0; i < RUNS; i += 1) runs.push(await measureOnce(name)); // 毎回新しいブラウザで
  return runs;
}

const bad = await measureRuns('s10-waterfall-bad');
const good = await measureRuns('s10-waterfall-good');
const badMs = median(bad.map((r) => r.durationMs));
const goodMs = median(good.map((r) => r.durationMs));
const ratio = goodMs / badMs;

console.log('[取得開始から表示完了まで（CPU 4倍スロットリング / 1,500kbps / RTT 40ms / 本番ビルド、3回の中央値）]');
console.log(`直列（Bad）: ${badMs.toFixed(0)}ms  各回 ${bad.map((r) => r.durationMs.toFixed(0)).join(' / ')}`);
console.log(`並列（Good）: ${goodMs.toFixed(0)}ms  各回 ${good.map((r) => r.durationMs.toFixed(0)).join(' / ')}`);
console.log(`比率（Good / Bad）: ${ratio.toFixed(2)}`);

check('Bad も Good も取得は 3 回', [...bad, ...good].every((r) => r.calls === 3));
check('Bad は同時に 1 本しか走らない（直列）', bad.every((r) => r.concurrency === 1));
check('Good は 3 本が同時に走る（並列）', good.every((r) => r.concurrency === 3));
check('Good の完了時間は Bad の 0.6 倍以下', ratio <= 0.6, `比率 ${ratio.toFixed(2)}`);

finish('S10 のウォーターフォール');
