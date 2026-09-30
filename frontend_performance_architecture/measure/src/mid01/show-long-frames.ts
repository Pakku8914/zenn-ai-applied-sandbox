import { collectVitals, withPage } from '../vitals-client.ts';
import { ms, pageUrl } from './lab.ts';

/**
 * 中間プロジェクト 問題7 の裏付け用：読み込み後に残っている長いフレーム（LoAF）を出す（判定はしない）。
 * 「後ろへ動かしただけ」の処理が、長いタスクとして残っているかを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/show-long-frames.ts mid01-fixed
 */
const name = process.argv[2] ?? 'mid01-fixed';
const MIN_DURATION_MS = 200;

type Frame = { startTime: number; duration: number; blockingDuration: number; invokers: string[] };

const frames = await withPage(async (page) => {
  await collectVitals(page, pageUrl(name));
  await page.waitForTimeout(1_000); // 入力はしない
  return page.evaluate(
    (min) =>
      new Promise<Frame[]>((resolve) => {
        // long-animation-frame は buffered: true で過去の記録も受け取れる
        new PerformanceObserver((list) => {
          resolve(
            list
              .getEntries()
              .map((entry) => {
                const e = entry as PerformanceEntry & {
                  blockingDuration: number;
                  scripts?: { invoker?: string; invokerType?: string }[];
                };
                return {
                  startTime: e.startTime,
                  duration: e.duration,
                  blockingDuration: e.blockingDuration,
                  invokers: (e.scripts ?? []).map((s) => `${s.invokerType ?? '?'}:${s.invoker ?? '?'}`),
                };
              })
              .filter((f) => f.duration >= min),
          );
        }).observe({ type: 'long-animation-frame', buffered: true });
        setTimeout(() => resolve([]), 1_000);
      }),
    MIN_DURATION_MS,
  );
});

console.log(`対象: ${name}（${MIN_DURATION_MS}ms 以上の長いフレーム）`);
if (frames.length === 0) console.log('該当するフレームはありません');
for (const f of frames) {
  console.log(`開始 ${ms(f.startTime)} / 長さ ${ms(f.duration)} / ブロック ${ms(f.blockingDuration)} / ${f.invokers.join(', ') || '（スクリプトの記録なし）'}`);
}
