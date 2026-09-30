import { createChecker, printTable } from './renders.ts';
import { NAMES, TYPED, TYPED_COUNT, expect, mismatches, runScope } from './scope.ts';

/**
 * S09：絞り込みを URL、カートを useSyncExternalStore の自作ストアに置いた版の再レンダリング範囲を確かめる。
 * Context 分割版との違いは「うち書籍」の表示：セレクタで選んだ値が変わらなければ再レンダリングされない。
 * 実行: docker compose exec measure node --experimental-strip-types src/session09/verify-store.ts
 */
const { check, finish } = createChecker();

const result = await runScope('s09-store');
printTable('s09-store', NAMES, {
  雑貨を追加: result.addNonBook,
  書籍を追加: result.addBook,
  [`「${TYPED}」を入力`]: result.typing,
});

const cases = [
  ['雑貨を追加すると、点数の表示だけが再レンダリングされる', result.addNonBook, expect({ CartBadge: 1 })],
  ['書籍を追加すると、点数と「うち書籍」が再レンダリングされる', result.addBook, expect({ CartBadge: 1, CartBookBadge: 1 })],
  // CategoryFilter はカテゴリだけを選んでいるので、キーワードが変わっても再レンダリングされない
  [`「${TYPED}」を入力すると、キーワードを読む部品だけが再レンダリングされる`, result.typing, expect({ SearchBox: 3, CatalogResults: 3, ResultList: 3 })],
] as const;

check(`入力後の件数が ${TYPED_COUNT} 件`, result.finalCount === TYPED_COUNT, `${result.finalCount} 件`);
for (const [name, actual, expected] of cases) {
  const diff = mismatches(actual, expected);
  check(name, diff === '', diff);
}

finish('S09 の外部ストア');
