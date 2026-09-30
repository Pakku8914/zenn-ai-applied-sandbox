import { withPage } from '../vitals-client.ts';
import { DONE, KEYWORD, MATCHED, START, TOTAL, countReached, createChecker, n } from './helpers.ts';

/**
 * 最終プロジェクト：絞り込みのキーワードを URL（?q=）に置いたことで、共有と戻る・進むが効くことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/final/verify-url.ts
 * 件数・URL・履歴の数は決定的なので完全一致で判定する。
 */
const SHARED_KEYWORD = '商品10';
/** 「商品10」を含む件数（商品10・100〜109・1000〜1099・10000〜10999） */
const SHARED_MATCHED = 1_111;
const { check, finish } = createChecker();

const withQuery = (url: string, q: string): string => `${url}?${new URLSearchParams({ q }).toString()}`;

await withPage(async (page) => {
  const inputValue = () => page.locator('#keyword').inputValue();
  const search = () => page.evaluate(() => location.search);
  const currentQ = () => page.evaluate(() => new URLSearchParams(location.search).get('q'));
  const historyLength = () => page.evaluate(() => history.length);

  // 1. 共有された URL を直接開く
  await page.goto(withQuery(DONE, SHARED_KEYWORD));
  check(`done: ?q=${SHARED_KEYWORD} を直接開くと ${n(SHARED_MATCHED)} 件`, await countReached(page, SHARED_MATCHED));
  check(`done: 入力欄にも「${SHARED_KEYWORD}」が入っている`, (await inputValue()) === SHARED_KEYWORD, await inputValue());
  const status = await page.locator('[role="status"]').textContent();
  check('done: ライブリージョンも開いた時点で件数を表す', status === '1,111 件見つかりました', String(status));

  await page.goto(withQuery(START, SHARED_KEYWORD));
  check(`start: ?q=${SHARED_KEYWORD} を開いても URL を読まないので ${n(TOTAL)} 件のまま`, await countReached(page, TOTAL));
  check('start: 入力欄は空（共有された条件が再現されない）', (await inputValue()) === '', await inputValue());

  // 2. 入力すると URL が変わり、履歴は 1 つだけ増える。戻る・進むで条件が戻る
  await page.goto(DONE);
  check(`done: 何も指定せずに開くと ${n(TOTAL)} 件`, await countReached(page, TOTAL));
  const before = await historyLength();
  await page.locator('#keyword').pressSequentially(KEYWORD, { delay: 60 });
  check(`done: 「${KEYWORD}」を入力すると ${n(MATCHED)} 件`, await countReached(page, MATCHED));
  check(`done: URL の q が「${KEYWORD}」になる`, (await currentQ()) === KEYWORD, String(await currentQ()));
  const added = (await historyLength()) - before;
  check('done: 3 文字入力しても履歴は 1 つだけ増える', added === 1, `${added} 件増加`);
  await page.goBack();
  check(`done: 戻ると入力前の ${n(TOTAL)} 件に戻る`, await countReached(page, TOTAL));
  check('done: 戻ると入力欄も空に戻る', (await inputValue()) === '', await inputValue());
  await page.goForward();
  check(`done: 進むと ${n(MATCHED)} 件に戻る`, await countReached(page, MATCHED));
  check(`done: 進むと入力欄も「${KEYWORD}」に戻る`, (await inputValue()) === KEYWORD, await inputValue());

  await page.goto(START);
  check(`start: 何も指定せずに開くと ${n(TOTAL)} 件`, await countReached(page, TOTAL));
  const startBefore = await historyLength();
  await page.locator('#keyword').pressSequentially(KEYWORD, { delay: 60 });
  check(`start: 「${KEYWORD}」を入力すると ${n(MATCHED)} 件`, await countReached(page, MATCHED));
  check('start: URL は変わらない（条件を共有できない）', (await search()) === '', await search());
  check('start: 履歴も増えない（戻ると絞り込みごとページを離れる）', (await historyLength()) === startBefore);
});

finish('最終プロジェクトの URL 状態');
