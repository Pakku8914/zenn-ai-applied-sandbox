import { collectVitals, withPage } from '../vitals-client.ts';
import { buildMilestones, readSnapshot, round1 } from './entries.ts';

/**
 * 出発点ページの performance エントリ（navigation・resource・paint）を列挙し、
 * ナビゲーション開始から FCP までの内訳を表で表示する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session02/show-entries.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';

const snap = await withPage(async (page) => {
  // LCP が報告されるまで待ってから読む（早すぎると paint エントリがまだ無い）
  await collectVitals(page, TARGET);
  return readSnapshot(page);
});

const nav = snap.navigation[0];
if (!nav) throw new Error('navigation エントリがありません');

console.log('--- navigation（ページ本体の取得と解析） ---');
console.table({
  type: nav.type,
  responseStart: round1(nav.responseStart),
  responseEnd: round1(nav.responseEnd),
  domInteractive: round1(nav.domInteractive),
  domContentLoadedEventEnd: round1(nav.domContentLoadedEventEnd),
  loadEventEnd: round1(nav.loadEventEnd),
});

console.log('--- resource（HTML から読み込んだファイル） ---');
console.table(
  snap.resources.map((r) => ({
    path: r.path,
    initiatorType: r.initiatorType,
    startTime: round1(r.startTime),
    responseEnd: round1(r.responseEnd),
    transferSize: r.transferSize,
    decodedBodySize: r.decodedBodySize,
  })),
);

console.log('--- paint（最初の描画） ---');
console.table(snap.paints.map((p) => ({ name: p.name, startTime: round1(p.startTime) })));

console.log('--- ナビゲーション開始から FCP までの内訳 ---');
console.table(buildMilestones(snap));
