import { withPage } from '../vitals-client.ts';
import { BAD, GOOD, READY, createChecker, focused, pressTab, tryWait, waitReady } from './helpers.ts';

/**
 * S16：待ち時間（aria-busy・スケルトン）・楽観的UI・エラー（role="alert"）の伝え方を検証する。
 * ?latency=10000 で読み込みを長引かせ、?fail=load / ?fail=favorite で失敗を再現する（乱数は使わない）。
 * 実行: docker compose exec measure node --experimental-strip-types src/session16/verify-feedback.ts
 */
const { check, finish } = createChecker();

const LOAD_ERROR = '商品を読み込めませんでした（503）。通信状態を確認して「もう一度読み込む」を押してください。';
const SAVE_ERROR = '商品1 をお気に入りに保存できませんでした。通信状態を確認して、もう一度押してください。';
const LIST = 'section[aria-labelledby="list-heading"]';

// --- 1. 読み込み中：aria-busy と status、スケルトンは読み上げない ---
await withPage(async (page) => {
  await page.goto(`${GOOD}?latency=10000`);
  await page.waitForSelector('[data-skeleton]');
  const busy = await page.locator(LIST).getAttribute('aria-busy');
  const status = await page.getByRole('status').textContent();
  const hidden = await page.locator('[data-skeleton]').getAttribute('aria-hidden');
  check('読み込み中: 一覧の領域が aria-busy="true"', busy === 'true', String(busy));
  check('読み込み中: status が「商品を読み込んでいます」', status === '商品を読み込んでいます', String(status));
  check('読み込み中: スケルトンは aria-hidden="true"', hidden === 'true', String(hidden));
});

await withPage(async (page) => {
  await page.goto(GOOD);
  await waitReady(page, 'good');
  const busy = await page.locator(LIST).getAttribute('aria-busy');
  check('読み込み後: aria-busy="false" になり、status が READY', busy === 'false', String(busy));
});

// --- 2. 読み込み失敗：alert・次の操作・押したあとのフォーカス ---
await withPage(async (page) => {
  await page.goto(`${GOOD}?fail=load`);
  await page.waitForSelector('[role="alert"]');
  const text = await page.locator('[role="alert"] p').textContent();
  check('読み込み失敗: role="alert" で原因と次の操作を伝える', text === LOAD_ERROR, String(text));

  const order = (await pressTab(page, 3)).join(' > ');
  check('読み込み失敗: Tab 3 回目で「もう一度読み込む」に届く', order === '#keyword > radio:すべて > button:もう一度読み込む', order);
  await page.keyboard.press('Enter');
  const afterRetry = await focused(page);
  check('再読み込み: 押したボタンが消えても、フォーカスは一覧の見出しへ移る', afterRetry === '#list-heading', afterRetry);
  await waitReady(page, 'good');
  const alerts = await page.locator('[role="alert"]').count();
  check('再読み込み: 成功したら alert が消え、status が READY', alerts === 0 && (await page.getByRole('status').textContent()) === READY, `alert ${alerts} 個`);
});

// --- 3. 楽観的UI：押した瞬間に切り替え、失敗したら戻して alert ---
await withPage(async (page) => {
  await page.goto(`${GOOD}?fail=favorite`);
  await waitReady(page, 'good');
  await pressTab(page, 3);
  await page.keyboard.press('Enter');
  await tryWait(page, `document.querySelector('dialog')?.open === true`);

  const favorite = page.locator('dialog button[aria-pressed]');
  const before = await favorite.getAttribute('aria-pressed');
  await favorite.click();
  const optimistic = await favorite.getAttribute('aria-pressed');
  check('お気に入り: 押した直後（応答 800ms を待たずに）aria-pressed="true"', before === 'false' && optimistic === 'true', `${before} → ${optimistic}`);

  await tryWait(page, `document.querySelector('dialog [role="alert"]') !== null`);
  const alert = await page.locator('dialog [role="alert"]').textContent();
  const rolledBack = await favorite.getAttribute('aria-pressed');
  check('お気に入り: 保存に失敗したら aria-pressed="false" に戻す', rolledBack === 'false', String(rolledBack));
  check('お気に入り: 失敗はダイアログの中の role="alert" で伝える', alert === SAVE_ERROR, String(alert));
});

// --- 4. Bad 版：失敗が見た目の「エラー」だけ ---
await withPage(async (page) => {
  await page.goto(`${BAD}?fail=load`);
  await page.getByText('エラー', { exact: true }).waitFor({ timeout: 15_000 });
  const alerts = await page.locator('[role="alert"]').count();
  const statuses = await page.locator('[role="status"]').count();
  check('bad: 失敗は「エラー」の文字だけで、alert も status も無い', alerts === 0 && statuses === 0, `alert ${alerts} / status ${statuses}`);
});

finish('S16 の待ち時間とエラーの伝え方');
