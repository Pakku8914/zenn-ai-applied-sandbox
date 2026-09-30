import { withPage } from '../vitals-client.ts';
import { createChecker, pageUrl, readCalls, readResult, waitForSettled } from './helpers.ts';

/**
 * S10：キーごとのキャッシュで、(1) 古い応答が画面を上書きしない (2) 一度取ったキーは新鮮な間は取り直さない、を確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session10/verify-cache.ts
 * 件数・キーワード・呼び出し回数は決定的なので完全一致で判定する。
 */
const { check, finish } = createChecker();

await withPage(async (page) => {
  await page.goto(pageUrl('s10-cache'), { waitUntil: 'load' });
  await waitForSettled(page, 1);
  check('開いた直後は「」の 2000 件', JSON.stringify(await readResult(page)) === '{"count":2000,"keyword":""}');

  // 1回目の入力：「商」「商品」「商品1」の3キーを取得する。応答の順序は逆でも、画面は「いまのキー」だけを読む
  await page.locator('#keyword').pressSequentially('商品1', { delay: 60 });
  await waitForSettled(page, 4);
  const first = await readResult(page);
  check('1回目：画面は「商品1」の 1111 件（古い応答に上書きされない）', first.keyword === '商品1' && first.count === 1111);
  const afterFirst = (await readCalls(page)).length;
  check('1回目：取得は「」「商」「商品」「商品1」の 4 回', afterFirst === 4, `${afterFirst} 回`);

  // 入力を消して打ち直す：どのキーも新鮮（30 秒以内）なので、1回も通信しない
  await page.locator('#keyword').fill('');
  await page.waitForTimeout(300); // 再レンダリングを待つ（通信は起きないので、待ち時間は描画のぶんだけ）
  const cleared = await readResult(page);
  check('消すと、通信せずにキャッシュから「」の 2000 件', cleared.keyword === '' && cleared.count === 2000);
  await page.locator('#keyword').pressSequentially('商品1', { delay: 60 });
  await page.waitForTimeout(500);
  const second = await readResult(page);
  const afterSecond = (await readCalls(page)).length;
  check('2回目：画面は「商品1」の 1111 件', second.keyword === '商品1' && second.count === 1111);
  check('2回目：取得は 0 回（呼び出しは 4 回のまま）', afterSecond === 4, `${afterSecond} 回`);
});

finish('S10 のキャッシュ');
