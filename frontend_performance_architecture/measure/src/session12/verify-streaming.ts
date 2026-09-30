import { measureMedian, withPage } from '../vitals-client.ts';
import { createChecker, nextUrl, streamTimeline } from './helpers.ts';

/**
 * S12：Suspense 境界で遅いデータを後から流す（ストリーミング）と、先頭で await して待たせる版の比較。
 * 実行: docker compose exec measure node --experimental-strip-types src/session12/verify-streaming.ts
 * 届く順序と「待ち時間より前か後か」は決定的に判定し、LCP・TTFB は大小で判定する。
 */
const { check, finish } = createChecker();
const DELAY = 1500; // next/lib/s12/ranking.ts の RANKING_DELAY_MS

// 1. HTML をストリームのまま読む
const stream = await streamTimeline(nextUrl('s12-stream'), {
  heading: '商品カタログ（ストリーミング版）',
  fallback: 'id="ranking-fallback"',
  ranking: 'id="ranking"',
});
const blocking = await streamTimeline(nextUrl('s12-blocking'), {
  heading: '商品カタログ（待たせる版）',
  ranking: 'id="ranking"',
});
console.log(
  `ストリーミング版: 最初のチャンク ${stream.firstChunkMs}ms / fallback ${stream.at.fallback}ms / ランキング ${stream.at.ranking}ms`,
);
console.log(`待たせる版    : 最初のチャンク ${blocking.firstChunkMs}ms / ランキング ${blocking.at.ranking}ms`);

const sFallback = stream.at.fallback ?? Infinity;
const sRanking = stream.at.ranking ?? -1;
check('ストリーミング版：最初のチャンクは遅いデータを待たずに届く', stream.firstChunkMs < DELAY - 500);
check('ストリーミング版：見出しと fallback が、ランキングより先に届く', (stream.at.heading ?? Infinity) <= sFallback && sFallback < sRanking);
check('ストリーミング版：ランキングは待ち時間のあとに届く', sRanking >= DELAY - 100);
check('待たせる版：最初のチャンクから待ち時間のあと', blocking.firstChunkMs >= DELAY - 100);
check('待たせる版：fallback は存在しない', !blocking.html.includes('ranking-fallback'));

// 2. ブラウザで「fallback が見えてから、ランキングに入れ替わる」ことを確かめる
await withPage(async (page) => {
  await page.goto(nextUrl('s12-stream'), { waitUntil: 'commit' });
  await page.waitForSelector('#ranking-fallback', { timeout: 15_000 });
  const fallbackVisibleFirst = (await page.locator('#ranking').count()) === 0;
  await page.waitForSelector('#ranking', { timeout: 15_000 });
  const rows = await page.locator('#ranking li').count();
  const fallbackLeft = await page.locator('#ranking-fallback').count();
  check('ブラウザ：先に fallback だけが見えている', fallbackVisibleFirst);
  check('ブラウザ：ランキング 5 件に入れ替わり、fallback は消える', rows === 5 && fallbackLeft === 0, `${rows} 件`);
});

// 3. LCP・TTFB を中央値で比べる
const s = await measureMedian(nextUrl('s12-stream'));
const b = await measureMedian(nextUrl('s12-blocking'));
console.log('\n| 版 | TTFB（中央値） | LCP（中央値） |');
console.log('| :--- | ---: | ---: |');
console.log(`| ストリーミング版 | ${Math.round(s.median.TTFB ?? NaN)}ms | ${Math.round(s.median.LCP ?? NaN)}ms |`);
console.log(`| 待たせる版 | ${Math.round(b.median.TTFB ?? NaN)}ms | ${Math.round(b.median.LCP ?? NaN)}ms |`);
check('TTFB：ストリーミング版 < 待たせる版', (s.median.TTFB ?? Infinity) < (b.median.TTFB ?? -1));
check('LCP：ストリーミング版 < 待たせる版', (s.median.LCP ?? Infinity) < (b.median.LCP ?? -1));

finish('S12 のストリーミング');
