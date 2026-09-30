import { withPage } from '../vitals-client.ts';
import { createChecker, pageUrl, readCalls, readResult, waitForSettled } from './helpers.ts';

/**
 * S10：後から届いた古い応答が画面を上書きする競合状態を再現し、中断（AbortController）で直ったことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session10/verify-race.ts
 * 擬似 API はキーワードが短いほど遅い（「商」700ms、「商品」500ms、「商品1」300ms）。
 * 表示された件数・キーワード・呼び出しの結果は決定的なので完全一致で判定する。
 */
const { check, finish } = createChecker();

async function typeAndSettle(name: string) {
  return withPage(async (page) => {
    await page.goto(pageUrl(name), { waitUntil: 'load' });
    await waitForSettled(page, 1); // 最初の '' の検索（900ms）が終わるまで待つ
    const initial = await readResult(page);
    await page.locator('#keyword').pressSequentially('商品1', { delay: 60 });
    await waitForSettled(page, 4);
    return {
      initial,
      final: await readResult(page),
      input: await page.locator('#keyword').inputValue(),
      outcomes: (await readCalls(page)).map((c) => `${c.key || '（空）'}:${c.outcome}`),
    };
  });
}

const bad = await typeAndSettle('s10-race-bad');
console.log('[Bad]', JSON.stringify(bad));
check('Bad：開いた直後は「」の 2000 件', bad.initial.count === 2000 && bad.initial.keyword === '');
check('Bad：入力欄は「商品1」', bad.input === '商品1');
check(
  'Bad：画面に残ったのは最後に届いた「商」の結果（2000 件）＝入力と食い違う',
  bad.final.keyword === '商' && bad.final.count === 2000,
  `「${bad.final.keyword}」${bad.final.count} 件`,
);
check('Bad：4 回の検索がすべて最後まで走る', bad.outcomes.join(',') === '（空）:ok,商:ok,商品:ok,商品1:ok');

const good = await typeAndSettle('s10-race-good');
console.log('[Good]', JSON.stringify(good));
check('Good：開いた直後は「」の 2000 件', good.initial.count === 2000 && good.initial.keyword === '');
check(
  'Good：画面には入力どおり「商品1」の結果（1111 件）',
  good.final.keyword === '商品1' && good.final.count === 1111,
  `「${good.final.keyword}」${good.final.count} 件`,
);
check('Good：途中の「商」「商品」は中断される', good.outcomes.join(',') === '（空）:ok,商:aborted,商品:aborted,商品1:ok');

finish('S10 の競合状態');
