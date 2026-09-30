import { collectVitals, interactAndCollect, median, withPage } from '../vitals-client.ts';
import { measureStyleCost } from './style-cost.ts';

/**
 * セッション2 の検証（その2）：メインスレッド・フレーム予算・レイアウトのコスト。
 * 時間の絶対値は環境で変わるため、判定は大小関係と件数の一致で行う。
 * BLOCK_MS でメインスレッドを塞ぐ時間を変えられる（例：-e BLOCK_MS=300）。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const BLOCK_MS = Number(process.env.BLOCK_MS ?? '200');
const FRAME_BUDGET_MS = 1000 / 60; // 60Hz の画面で 1 フレームに使える時間（約 16.7ms）
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const fmt = (ms: number): string => `${ms.toFixed(1)}ms`;

const result = await withPage(async (page) => {
  await collectVitals(page, TARGET);

  // (1) 何もしていないときのフレーム間隔を 60 回ぶん記録する
  const intervals = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const stamps: number[] = [];
        const tick = (t: number): void => {
          stamps.push(t);
          if (stamps.length <= 60) {
            requestAnimationFrame(tick);
            return;
          }
          resolve(stamps.slice(1).map((s, i) => s - stamps[i]!));
        };
        requestAnimationFrame(tick);
      }),
  );

  // (2) setTimeout(0) を予約した直後に、メインスレッドを BLOCK_MS だけ塞ぐ
  const blocked = await page.evaluate(
    (blockMs) =>
      new Promise<{ busyMs: number; timerDelayMs: number }>((resolve) => {
        const scheduledAt = performance.now();
        let busyMs = 0;
        setTimeout(() => resolve({ busyMs, timerDelayMs: performance.now() - scheduledAt }), 0);
        const start = performance.now();
        while (performance.now() - start < blockMs) {
          // 何もせずに回り続ける＝メインスレッドを占有する
        }
        busyMs = performance.now() - start;
      }),
    BLOCK_MS,
  );

  // (3) 2,000 件のまま、変更の種類ごとの計算コストを測る
  const items2000 = await page.locator('section ul li').count();
  const cost2000 = await measureStyleCost(page);

  // (4) 「商品10」で 111 件に絞ってから、同じ計測をする
  await interactAndCollect(page, '#keyword', '商品10');
  const items111 = await page.locator('section ul li').count();
  const cost111 = await measureStyleCost(page);

  return { intervals, blocked, items2000, cost2000, items111, cost111 };
});

const frame = median(result.intervals);
check('何もしていないときのフレーム間隔はおよそ 1 フレーム（16.7ms）', frame >= 5 && frame <= 50, fmt(frame));

const { busyMs, timerDelayMs } = result.blocked;
check(
  `メインスレッドを ${BLOCK_MS}ms 塞ぐと setTimeout(0) も待たされる`,
  timerDelayMs >= BLOCK_MS,
  `塞いだ時間 ${fmt(busyMs)} / タイマーの遅れ ${fmt(timerDelayMs)}（描けなかったフレーム 約 ${Math.round(busyMs / FRAME_BUDGET_MS)} 枚）`,
);

const c2 = result.cost2000;
const c1 = result.cost111;
check('商品リストが 2,000 件ある', result.items2000 === 2000, `${result.items2000} 件`);
check('幅の変更（レイアウト）は背景色の変更（ペイント）より計算が重い', c2.layout > c2.paint, `${fmt(c2.layout)} > ${fmt(c2.paint)}`);
check('幅の変更（レイアウト）は transform の変更（合成）より計算が重い', c2.layout > c2.composite, `${fmt(c2.layout)} > ${fmt(c2.composite)}`);
check('「商品10」で 111 件に絞り込める', result.items111 === 111, `${result.items111} 件`);
check('件数が減るとレイアウトの計算も軽くなる', c1.layout < c2.layout, `111 件 ${fmt(c1.layout)} < 2,000 件 ${fmt(c2.layout)}`);

console.log('');
console.log('変更の種類ごとの計算時間（中央値・ms）:');
const r2 = (v: number): number => Math.round(v * 100) / 100;
console.table([
  { 変更: 'width（レイアウトが要る）', '2,000件': r2(c2.layout), '111件': r2(c1.layout) },
  { 変更: 'background-color（ペイントだけ）', '2,000件': r2(c2.paint), '111件': r2(c1.paint) },
  { 変更: 'transform（合成だけ）', '2,000件': r2(c2.composite), '111件': r2(c1.composite) },
]);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nセッション2（メインスレッドとレイアウト）の検証に成功しました。');
