import type { Page } from 'playwright';
import { withPage } from '../vitals-client.ts';
import { createChecker, pageUrl, readCalls, waitForSettled } from './helpers.ts';

/**
 * S10：楽観的更新（応答を待たずに画面を変える）と、失敗したときのロールバックを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session10/verify-optimistic.ts
 * 擬似 API の保存は 800ms かかり、商品3 だけが必ず失敗する。
 */
const { check, finish } = createChecker();

const pressed = (page: Page, id: number) => page.locator(`button[data-id="${id}"]`).getAttribute('aria-pressed');
const pending = async (page: Page) => (await readCalls(page)).filter((c) => c.endedAt === undefined).length;

await withPage(async (page) => {
  await page.goto(pageUrl('s10-optimistic'), { waitUntil: 'load' });
  await page.locator('button[data-id="1"]').waitFor();

  // 成功する操作：押した直後（応答前）に ★ になり、応答後もそのまま
  await page.locator('button[data-id="1"]').click();
  await page.waitForSelector('button[data-id="1"][aria-pressed="true"]', { timeout: 500 });
  check('商品1：押した直後、応答が届く前に ★ になる', (await pending(page)) === 1);
  await waitForSettled(page, 1);
  check('商品1：保存に成功し、★ のまま', (await pressed(page, 1)) === 'true');

  // 失敗する操作：いったん ★ になり、失敗の応答で ☆ に戻って通知が出る
  await page.locator('button[data-id="3"]').click();
  await page.waitForSelector('button[data-id="3"][aria-pressed="true"]', { timeout: 500 });
  check('商品3：押した直後、応答が届く前に ★ になる', (await pending(page)) === 1);
  await waitForSettled(page, 2);
  check('商品3：保存に失敗し、☆ に戻る', (await pressed(page, 3)) === 'false');
  check('商品1：他の商品の ★ は巻き戻されない', (await pressed(page, 1)) === 'true');
  const notice = await page.locator('#notice').textContent();
  check('失敗を利用者に知らせる', notice === '商品3 のお気に入りを保存できませんでした。元に戻しました。', notice ?? '');
  const outcomes = (await readCalls(page)).map((c) => `${c.key}:${c.outcome}`).join(',');
  check('保存の呼び出しは 2 回（失敗してもリトライしない）', outcomes === '1:ok,3:error', outcomes);
});

finish('S10 の楽観的更新');
