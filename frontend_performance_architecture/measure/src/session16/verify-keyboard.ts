import type { Page } from 'playwright';
import { withPage } from '../vitals-client.ts';
import { BAD, GOOD, createChecker, focused, pressTab, tryWait, waitReady } from './helpers.ts';

/**
 * S16：キーボードだけで操作したときのフォーカスの動きを、Bad 版と Good 版で比べる。
 * フォーカスの行き先は決定的なので、すべて完全一致で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session16/verify-keyboard.ts
 */
const { check, finish } = createChecker();

const outlineOf = (page: Page): Promise<string> =>
  page.evaluate(() => (document.activeElement ? getComputedStyle(document.activeElement).outlineStyle : 'なし'));

const checkedRadio = (page: Page): Promise<string | null> => page.locator('[role="radio"][aria-checked="true"]').textContent();

// --- Good 版 ---
await withPage(async (page) => {
  await page.goto(GOOD);
  await waitReady(page, 'good');

  const first = await pressTab(page, 1);
  const outline = await outlineOf(page);
  const rest = await pressTab(page, 2);
  const order = [...first, ...rest].join(' > ');
  console.log(`good の Tab 順序: ${order}`);
  check('good: Tab 順序が 入力欄 → カテゴリ（選択中の1つ）→ 一覧の今の行', order === '#keyword > radio:すべて > button:商品1', order);
  check('good: キーボードで入った入力欄に 3px の枠が出る（:focus-visible）', outline === 'solid', outline);

  // ロービングタブインデックス：グループの中は矢印で動く
  await page.keyboard.press('Shift+Tab');
  check('good: Shift+Tab でカテゴリに戻る', (await focused(page)) === 'radio:すべて', await focused(page));
  await page.keyboard.press('ArrowRight');
  check('good: → で「文具」へ移り、選択される', (await focused(page)) === 'radio:文具' && (await checkedRadio(page)) === '文具', await focused(page));
  await tryWait(page, `document.querySelector('[role="status"]')?.textContent === '500 件見つかりました'`);
  const status = await page.getByRole('status').textContent();
  check('good: ライブリージョンが「500 件見つかりました」になる', status === '500 件見つかりました', String(status));
  await page.keyboard.press('Tab');
  check('good: カテゴリから Tab 1 回で一覧の先頭（商品4）へ', (await focused(page)) === 'button:商品4', await focused(page));
  await page.keyboard.press('Shift+Tab');
  check('good: 戻ると選択中の「文具」にフォーカスが戻る', (await focused(page)) === 'radio:文具', await focused(page));
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  check('good: ← を 2 回で「すべて」→「食品」へ回り込む', (await focused(page)) === 'radio:食品', await focused(page));
  await page.keyboard.press('Home');
  check('good: Home で「すべて」', (await focused(page)) === 'radio:すべて', await focused(page));

  // ダイアログ：開いたら中へ、閉じたら元の行へ
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await tryWait(page, `document.querySelector('dialog')?.open === true`);
  const inDialog = await focused(page);
  const title = await page.locator('dialog h2').textContent();
  const labelled = await page.locator('dialog').getAttribute('aria-labelledby');
  check('good: Enter でダイアログが開き、「閉じる」にフォーカスが移る', inDialog === 'button:閉じる', inDialog);
  check('good: ダイアログの名前は見出し「商品1 の詳細」', title === '商品1 の詳細' && labelled === 'dialog-title', `${title} / ${labelled}`);
  await page.keyboard.press('Escape');
  await tryWait(page, `document.querySelector('dialog')?.open === false`);
  const back = await focused(page);
  check('good: Escape で閉じ、開く前の行（商品1）にフォーカスが戻る', back === 'button:商品1', back);
});

// --- Bad 版 ---
await withPage(async (page) => {
  await page.goto(BAD);
  await waitReady(page, 'bad');

  const first = await pressTab(page, 1);
  const outline = await outlineOf(page);
  const rest = await pressTab(page, 2);
  const order = [...first, ...rest].join(' > ');
  console.log(`bad の Tab 順序: ${order}`);
  check('bad: カテゴリ（div）は Tab で止まらず、行が 1 つずつ Tab に並ぶ', order === '#keyword > li:商品1 > li:商品2', order);
  check('bad: フォーカスの枠が消されている（outline: none）', outline === 'none', outline);

  await page.locator('[data-viewport] li').first().click();
  const afterOpen = await focused(page);
  check('bad: ダイアログを開いてもフォーカスは背後の行に残る', afterOpen === 'li:商品1', afterOpen);
  await page.keyboard.press('Escape');
  const stillOpen = await page.locator('[data-bad-dialog]').count();
  check('bad: Escape では閉じない', stillOpen === 1, `${stillOpen} 個`);
  await page.locator('[data-bad-dialog] button').click();
  const afterClose = await focused(page);
  check('bad: 「×」で閉じるとフォーカスが body に落ちる', afterClose === 'body', afterClose);
});

finish('S16 のキーボード操作');
