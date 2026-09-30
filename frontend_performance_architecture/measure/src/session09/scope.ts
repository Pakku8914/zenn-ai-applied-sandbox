import { collectVitals, interactAndCollect, withPage } from '../vitals-client.ts';
import { clickAdd, diffRenders, pageUrl, readRenders, waitForCount, type Renders } from './renders.ts';

/**
 * 再レンダリング範囲の比較で共通に使う操作の台本（verify-context.ts / verify-store.ts から使う）。
 * 1) 2行目（商品2・雑貨）をカートに入れる 2) 1行目（商品1・書籍）を入れる 3) 「商品1」を入力する
 */
export const NAMES = [
  'PageIntro',
  'SearchBox',
  'CategoryFilter',
  'CartBadge',
  'CartBookBadge',
  'CatalogResults',
  'ResultList',
] as const;

export const TYPED = '商品1';
export const TYPED_COUNT = 1111;

export type ScopeResult = {
  addNonBook: Renders;
  addBook: Renders;
  typing: Renders;
  finalCount: number | null;
};

export async function runScope(page: string): Promise<ScopeResult> {
  return withPage(async (p) => {
    // LCP を取ってから操作する（先に操作すると LCP が永久に取れない）
    await collectVitals(p, pageUrl(page));
    const r0 = await readRenders(p);
    await clickAdd(p, 1, 1);
    const r1 = await readRenders(p);
    await clickAdd(p, 0, 2);
    const r2 = await readRenders(p);
    await interactAndCollect(p, '#keyword', TYPED);
    const finalCount = await waitForCount(p, TYPED_COUNT);
    const r3 = await readRenders(p);
    return {
      addNonBook: diffRenders(r0, r1, NAMES),
      addBook: diffRenders(r1, r2, NAMES),
      typing: diffRenders(r2, r3, NAMES),
      finalCount,
    };
  });
}

/** 期待値の書き方を短くする：書いていないコンポーネントは 0 回 */
export function expect(partial: Partial<Record<(typeof NAMES)[number], number>>): Renders {
  return Object.fromEntries(NAMES.map((n) => [n, partial[n] ?? 0]));
}

export function mismatches(actual: Renders, expected: Renders): string {
  return NAMES.filter((n) => actual[n] !== expected[n])
    .map((n) => `${n}: 期待 ${expected[n]} / 実際 ${actual[n]}`)
    .join(', ');
}
