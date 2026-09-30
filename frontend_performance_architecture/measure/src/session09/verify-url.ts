import { withPage } from '../vitals-client.ts';
import { createChecker, pageUrl, waitForCount } from './renders.ts';

/**
 * S09：絞り込みの状態を URL に置いた版が、共有（URL を直接開く）と戻る・進むで正しく動くことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session09/verify-url.ts
 * 件数・URL・履歴の数は決定的なので完全一致で判定する。
 */
const PAGE = 's09-url-state';
const { check, finish } = createChecker();

const query = (params: Record<string, string>): string => `?${new URLSearchParams(params).toString()}`;

await withPage(async (page) => {
  const inputValue = () => page.locator('#keyword').inputValue();
  const selectValue = () => page.locator('#category').inputValue();
  const currentQ = () => page.evaluate(() => new URLSearchParams(location.search).get('q'));
  const historyLength = () => page.evaluate(() => history.length);

  // 1. 共有された URL を直接開く
  await page.goto(pageUrl(PAGE, '?q=商品10'));
  check('?q=商品10 を直接開くと 111 件', (await waitForCount(page, 111)) === 111);
  check('入力欄にも「商品10」が入っている', (await inputValue()) === '商品10');

  await page.goto(pageUrl(PAGE, query({ q: '商品10', category: '書籍' })));
  check('?q=商品10&category=書籍 を直接開くと 28 件', (await waitForCount(page, 28)) === 28);
  check('カテゴリの選択も「書籍」になっている', (await selectValue()) === '書籍');

  // 2. URL は外部入力。知らない値・HTML を含む値でも壊れない
  await page.goto(pageUrl(PAGE, query({ category: '家電' })));
  check('知らないカテゴリ（家電）は「すべて」扱いで 2000 件', (await waitForCount(page, 2000)) === 2000);

  const payload = '<img src=x onerror="window.__xss=1">';
  await page.goto(pageUrl(PAGE, query({ q: payload })));
  const imgCount = await page.locator('main img').count();
  const xss = await page.evaluate(() => (window as unknown as { __xss?: number }).__xss ?? 0);
  check('HTML を含むキーワードは文字列として扱われる（img 要素ができない）', imgCount === 0 && xss === 0);
  check('そのキーワードに一致する商品は 0 件', (await waitForCount(page, 0)) === 0);

  // 3. 入力すると URL が変わり、履歴は1つだけ増える
  await page.goto(pageUrl(PAGE));
  check('何も指定せずに開くと 2000 件', (await waitForCount(page, 2000)) === 2000);
  const before = await historyLength();
  await page.locator('#keyword').pressSequentially('商品10', { delay: 60 });
  check('「商品10」を入力すると 111 件', (await waitForCount(page, 111)) === 111);
  check('URL の q が「商品10」になる', (await currentQ()) === '商品10');
  const added = (await historyLength()) - before;
  check('4文字入力しても履歴は1つだけ増える（最初の1文字で push、続きは replace）', added === 1, `${added} 件増加`);

  // 4. 戻る・進む
  await page.goBack();
  check('戻ると入力前の 2000 件に戻る', (await waitForCount(page, 2000)) === 2000);
  check('戻ると入力欄も空に戻る', (await inputValue()) === '');
  await page.goForward();
  check('進むと 111 件に戻る', (await waitForCount(page, 111)) === 111);

  // 5. 確定操作（カテゴリの選択）は1回ごとに積む
  await page.locator('#category').selectOption('書籍');
  check('カテゴリで「書籍」を選ぶと 28 件', (await waitForCount(page, 28)) === 28);
  check('選択で履歴がさらに1つ増える', (await historyLength()) - before === 2);
  await page.goBack();
  check('戻るとカテゴリが「すべて」の 111 件に戻る', (await waitForCount(page, 111)) === 111);
  check('戻るとカテゴリの選択も「すべて」に戻る', (await selectValue()) === 'すべて');
});

finish('S09 の URL 状態');
