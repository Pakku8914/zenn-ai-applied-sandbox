import type { Page } from 'playwright';
import { jsBytes, withPage } from '../vitals-client.ts';
import { DONE, KEYWORD, MATCHED, START, TOTAL, createChecker, focused, n, pressTab, tryWait, waitForCount } from './helpers.ts';

/**
 * 最終プロジェクト：キーボードだけの操作・フォーカスの行き先・件数の読み上げを、出題版と模範解答版で比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/final/verify-a11y.ts
 * フォーカスの行き先・読み上げの文・行数は決定的なので、すべて完全一致で判定する。
 */
const READY = '全 20,000 件を表示しています';
const FOUND = '11,111 件見つかりました';
const { check, finish } = createChecker();

declare global {
  interface Window {
    __finalStatusLog?: string[];
  }
}

const rowCount = (page: Page): Promise<number> =>
  page.evaluate(() => document.querySelectorAll('section ul li').length);

// --- 模範解答版 ---
await withPage(async (page) => {
  await page.goto(DONE);
  await waitForCount(page, TOTAL);
  const status = await page.locator('[role="status"]').textContent();
  check(`done: 開いた直後のライブリージョンは「${READY}」`, status === READY, String(status));

  const order = (await pressTab(page, 3)).join(' > ');
  console.log(`done の Tab 順序: ${order}`);
  check('done: Tab 順序が 入力欄 → グラフのボタン → 一覧の今の行', order === '#keyword > button:グラフを表示 > button:商品1', order);

  await page.keyboard.press('ArrowDown');
  check('done: ↓ で次の行（商品2）へ', (await focused(page)) === 'button:商品2', await focused(page));
  await page.keyboard.press('End');
  await page.waitForTimeout(300);
  const last = await focused(page);
  const rowsAtEnd = await rowCount(page);
  check(
    `done: End で最後の行（商品${TOTAL}）へ移り、DOM の行は 16 以下のまま`,
    last === `button:商品${TOTAL}` && rowsAtEnd <= 16,
    `${last} / ${rowsAtEnd} 行`,
  );
  await page.keyboard.press('Home');
  check('done: Home で先頭（商品1）に戻る', (await focused(page)) === 'button:商品1', await focused(page));
  await page.keyboard.press('Shift+Tab');
  check('done: 一覧は Tab 1 回分。Shift+Tab でグラフのボタンに戻る', (await focused(page)) === 'button:グラフを表示', await focused(page));
  await page.keyboard.press('Tab');

  // 印刷：Enter で選ぶと、そのとき初めて印刷用の部品を読み込む。フォーカスは行に残る
  const jsBefore = await jsBytes(page);
  await page.keyboard.press('Enter');
  await tryWait(page, `document.querySelector('#print-output')?.textContent?.includes('<h2>商品1</h2>') === true`);
  const printed = (await page.locator('#print-output').textContent()) ?? '';
  const jsAfter = await jsBytes(page);
  check('done: Enter で「商品1」の印刷用 HTML ができる', printed.includes('<h2>商品1</h2>'), printed.slice(0, 60));
  check('done: 選んだ後もフォーカスは「商品1」の行に残る', (await focused(page)) === 'button:商品1', await focused(page));
  check('done: 印刷用の部品は選んだときに初めて読み込まれる', jsAfter > jsBefore, `+${n(jsAfter - jsBefore)} バイト`);

  // 件数の読み上げ：打ち終わってから 1 回だけ
  await page.evaluate(() => {
    const log: string[] = [];
    window.__finalStatusLog = log;
    const el = document.querySelector('[role="status"]');
    if (el === null) return;
    new MutationObserver(() => {
      const text = el.textContent ?? '';
      if (log.at(-1) !== text) log.push(text);
    }).observe(el, { childList: true, characterData: true, subtree: true });
  });
  await page.locator('#keyword').pressSequentially(KEYWORD, { delay: 60 });
  await waitForCount(page, MATCHED);
  await tryWait(page, `document.querySelector('[role="status"]')?.textContent === '${FOUND}'`);
  const log = await page.evaluate(() => window.__finalStatusLog ?? []);
  check(`done: 3 文字打っても読み上げは打ち終わった後の 1 回（「${FOUND}」）だけ`, log.join('|') === FOUND, log.join(' / '));
});

// --- 出題版 ---
await withPage(async (page) => {
  await page.goto(START);
  await waitForCount(page, TOTAL);
  const order = (await pressTab(page, 4)).join(' > ');
  console.log(`start の Tab 順序: ${order}`);
  check(
    `start: 行のボタンが 1 つずつ Tab に並ぶ（一覧を抜けるのに ${n(TOTAL)} 回かかる）`,
    order === '#keyword > button:グラフを表示 > button:商品1 > button:商品2',
    order,
  );
  const statusCount = await page.locator('[role="status"]').count();
  check('start: ライブリージョンが無い（件数が変わっても読み上げられない）', statusCount === 0, `${statusCount} 個`);
});

finish('最終プロジェクトのアクセシビリティ');
