import { collectVitals, interactAndCollect, withPage } from '../vitals-client.ts';
import { createChecker, diffRenders, pageUrl, readRenders, waitForCount } from './renders.ts';

/**
 * S09：派生状態（絞り込み結果）を state に写した Bad 版と、毎回計算する版の再レンダリング回数を比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session09/verify-derived.ts
 */
const { check, finish } = createChecker();
const NAMES = ['CatalogResults', 'ResultList'] as const;
const TYPED = '商品1';

async function typingRenders(page: string) {
  return withPage(async (p) => {
    await collectVitals(p, pageUrl(page));
    const before = await readRenders(p);
    await interactAndCollect(p, '#keyword', TYPED);
    const count = await waitForCount(p, 1111);
    return { renders: diffRenders(before, await readRenders(p), NAMES), count };
  });
}

const computed = await typingRenders('s09-url-state');
const synced = await typingRenders('s09-derived-bad');

console.log(`「${TYPED}」（3文字）を入力したときの再レンダリング回数`);
console.log(`s09-url-state（計算で出す）      : CatalogResults ${computed.renders.CatalogResults} / ResultList ${computed.renders.ResultList}`);
console.log(`s09-derived-bad（state に写す）  : CatalogResults ${synced.renders.CatalogResults} / ResultList ${synced.renders.ResultList}`);

check('どちらも最終的な件数は 1111 件', computed.count === 1111 && synced.count === 1111, `${computed.count} / ${synced.count}`);
check('計算で出す版は1文字につき1回（3回）', computed.renders.CatalogResults === 3 && computed.renders.ResultList === 3);
// 1文字ごとに間を空ければ 2 回ずつ（計 6 回）になるが、60ms 間隔で続けて打つと
// 前の文字の effect と次の文字の描画がまとまることがあり、回数はタイミングで変わる。
// そのため「計算で出す版より多い」ことだけを判定する。
check(
  'state に写す版は計算で出す版より多く再レンダリングされる',
  synced.renders.CatalogResults! > computed.renders.CatalogResults! && synced.renders.ResultList! > computed.renders.ResultList!,
);

finish('S09 の派生状態');
