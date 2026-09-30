import { CONDITIONS } from '../vitals-client.ts';
import { createChecker, printTable } from './renders.ts';
import { NAMES, TYPED, TYPED_COUNT, expect, mismatches, runScope, type ScopeResult } from './scope.ts';

/**
 * S09：Context に全状態を入れた Bad 版と、変わる頻度で分割した Good 版の再レンダリング範囲を比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session09/verify-context.ts
 * 回数は手動カウンタ（window.__s09RenderCount）の増分。決定的なので完全一致で判定する。
 */
const { check, finish } = createChecker();
const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド`,
);

const all = { SearchBox: 1, CategoryFilter: 1, CartBadge: 1, CartBookBadge: 1, CatalogResults: 1, ResultList: 1 };
const EXPECTED: Record<string, Omit<ScopeResult, 'finalCount'>> = {
  // 1つの値オブジェクトを全員が読んでいるので、何が変わっても全員が再レンダリングされる
  's09-context-bad': {
    addNonBook: expect(all),
    addBook: expect(all),
    typing: expect({ SearchBox: 3, CategoryFilter: 3, CartBadge: 3, CartBookBadge: 3, CatalogResults: 3, ResultList: 3 }),
  },
  // 変わった値の Context を読んでいる部品だけが再レンダリングされる
  's09-context-good': {
    addNonBook: expect({ CartBadge: 1, CartBookBadge: 1 }),
    addBook: expect({ CartBadge: 1, CartBookBadge: 1 }),
    typing: expect({ SearchBox: 3, CatalogResults: 3, ResultList: 3 }),
  },
};

for (const [page, expected] of Object.entries(EXPECTED)) {
  const result = await runScope(page);
  printTable(page, NAMES, {
    雑貨を追加: result.addNonBook,
    書籍を追加: result.addBook,
    [`「${TYPED}」を入力`]: result.typing,
  });
  check(`${page}：入力後の件数が ${TYPED_COUNT} 件`, result.finalCount === TYPED_COUNT, `${result.finalCount} 件`);
  check(`${page}：雑貨を追加したときの再レンダリング`, mismatches(result.addNonBook, expected.addNonBook) === '', mismatches(result.addNonBook, expected.addNonBook));
  check(`${page}：書籍を追加したときの再レンダリング`, mismatches(result.addBook, expected.addBook) === '', mismatches(result.addBook, expected.addBook));
  check(`${page}：「${TYPED}」（3文字）を入力したときの再レンダリング`, mismatches(result.typing, expected.typing) === '', mismatches(result.typing, expected.typing));
}

finish('S09 の Context 分割');
