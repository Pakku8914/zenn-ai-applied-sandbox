import type { Page } from 'playwright';
import { withPage } from '../vitals-client.ts';
import { BAD, GOOD, createChecker, focused, pressTab, rowCount, scrollTopOf, scrollViewport, tryWait, waitReady } from './helpers.ts';

/**
 * S16：仮想化した一覧で、フォーカス中の行がスクロールで表示範囲の外に出たときにフォーカスがどこへ行くかを比べる。
 * 行の高さ 40px・表示枠 400px・オーバースキャン 5 行（S11 と同じ）。値はすべて決定的なので完全一致で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session16/verify-virtual-focus.ts
 */
const { check, finish } = createChecker();

const focusedPos = (page: Page): Promise<string | null> =>
  page.evaluate(() => document.activeElement?.closest('li')?.getAttribute('aria-posinset') ?? null);

const focusedConnected = (page: Page): Promise<boolean> => page.evaluate(() => document.activeElement?.isConnected ?? false);

// --- Good 版：フォーカス中の行を DOM に残す ---
await withPage(async (page) => {
  await page.goto(GOOD);
  await waitReady(page, 'good');

  await pressTab(page, 3);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  check('good: ↓ 2 回で 商品3 へ', (await focused(page)) === 'button:商品3', await focused(page));

  await scrollViewport(page, 4_000);
  await tryWait(page, `document.querySelector('[data-viewport] li[aria-posinset="96"]') !== null`);
  const after = await focused(page);
  const rows = await rowCount(page);
  console.log(`good 4,000px までスクロール: フォーカス ${after} / DOM の行 ${rows}`);
  check('good: スクロール後もフォーカスは 商品3 のまま（body に落ちない）', after === 'button:商品3' && (await focusedConnected(page)), after);
  check('good: DOM の行は表示範囲の 20 行 + フォーカス中の 1 行 = 21 行', rows === 21, `${rows} 行`);
  check('good: フォーカス中の行の aria-posinset が 3', (await focusedPos(page)) === '3', String(await focusedPos(page)));

  await page.keyboard.press('ArrowDown');
  const top = await scrollTopOf(page);
  await tryWait(page, `document.querySelectorAll('[data-viewport] li').length === 18`);
  check('good: ↓ で 商品4 へ移り、その行が見える位置（scrollTop 120px）へ戻る', (await focused(page)) === 'button:商品4' && top === 120, `${await focused(page)} / ${top}px`);
  check('good: 戻った位置では DOM の行が 18 行', (await rowCount(page)) === 18, `${await rowCount(page)} 行`);

  await page.keyboard.press('End');
  const endTop = await scrollTopOf(page);
  await tryWait(page, `document.querySelectorAll('[data-viewport] li').length === 15`);
  const setsize = await page.evaluate(() => document.activeElement?.closest('li')?.getAttribute('aria-setsize') ?? null);
  check('good: End で 商品2000（aria-posinset 2000 / aria-setsize 2000）', (await focused(page)) === 'button:商品2000' && (await focusedPos(page)) === '2000' && setsize === '2000', `${await focused(page)} / ${await focusedPos(page)} / ${setsize}`);
  check('good: End で末尾まで（scrollTop 79,600px）スクロールし、DOM の行は 15 行', endTop === 79_600 && (await rowCount(page)) === 15, `${endTop}px / ${await rowCount(page)} 行`);
});

// --- Bad 版：表示範囲の行だけを置く（S11 と同じ）＋全行が Tab で止まる ---
await withPage(async (page) => {
  await page.goto(BAD);
  await waitReady(page, 'bad');

  await pressTab(page, 4);
  check('bad: Tab 4 回で 商品3 の行へ', (await focused(page)) === 'li:商品3', await focused(page));

  await scrollViewport(page, 4_000);
  await tryWait(page, `document.querySelector('[data-viewport] li span')?.textContent === '商品96'`);
  const after = await focused(page);
  console.log(`bad 4,000px までスクロール: フォーカス ${after} / DOM の行 ${await rowCount(page)}`);
  check('bad: 行が DOM から消え、フォーカスが body に落ちる', after === 'body', after);
});

finish('S16 の仮想化とフォーカス');
