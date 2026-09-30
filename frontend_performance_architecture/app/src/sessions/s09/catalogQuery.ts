import type { Product } from '../../data/products';

/** 絞り込みの状態。URL（`?q=…&category=…`）に置く。 */
export const CATEGORY_ALL = 'すべて';
export const CATEGORY_OPTIONS = [CATEGORY_ALL, '文具', '書籍', '雑貨', '食品'] as const;
export type CategoryOption = (typeof CATEGORY_OPTIONS)[number];

/** URL は利用者が自由に書き換えられる外部入力なので、長さに上限を設ける */
export const MAX_KEYWORD_LENGTH = 100;

export type CatalogQuery = {
  keyword: string;
  category: CategoryOption;
};

export const DEFAULT_QUERY: CatalogQuery = { keyword: '', category: CATEGORY_ALL };

function isCategory(value: string): value is CategoryOption {
  return (CATEGORY_OPTIONS as readonly string[]).includes(value);
}

/** 画面の選択肢から来た値を型に合わせる。知らない値は「すべて」に戻す。 */
export function toCategory(value: string): CategoryOption {
  return isCategory(value) ? value : CATEGORY_ALL;
}

/**
 * URL の検索部分を状態に変換する。
 * 共有された URL は誰が書いたものか分からないので、知らない値は既定値に戻す。
 */
export function parseCatalogQuery(search: string): CatalogQuery {
  const params = new URLSearchParams(search);
  return {
    keyword: (params.get('q') ?? '').slice(0, MAX_KEYWORD_LENGTH),
    category: toCategory(params.get('category') ?? CATEGORY_ALL),
  };
}

/**
 * 状態を URL の検索部分に変換する。
 * 既定値は書かない（同じ状態が必ず同じ URL になり、共有される URL も短くなる）。
 */
export function toSearch(query: CatalogQuery): string {
  const params = new URLSearchParams();
  if (query.keyword !== '') params.set('q', query.keyword);
  if (query.category !== CATEGORY_ALL) params.set('category', query.category);
  const search = params.toString();
  return search === '' ? '' : `?${search}`;
}

/** 表示する商品は状態から毎回計算する（派生状態を state に持たない） */
export function filterProducts(items: readonly Product[], query: CatalogQuery): Product[] {
  return items.filter(
    (p) =>
      p.name.includes(query.keyword) && (query.category === CATEGORY_ALL || p.category === query.category),
  );
}

/** カートの中の、指定カテゴリの商品数 */
export function countInCategory(ids: readonly number[], category: string, items: readonly Product[]): number {
  return ids.filter((id) => items.find((p) => p.id === id)?.category === category).length;
}

export type HistoryMode = 'push' | 'replace';
/** typing：1文字ずつの入力 / commit：選択肢を選ぶなど、1回で確定する操作 */
export type ChangeKind = 'typing' | 'commit';

/**
 * 履歴の積み方を決める。
 * - 確定操作は1回ごとに積む（戻る操作で1つ前の選択に戻れる）
 * - 入力は最初の1文字でだけ積み、続きは置き換える（1文字ごとに履歴が増えない）
 */
export function decideHistoryMode(typing: boolean, kind: ChangeKind): HistoryMode {
  if (kind === 'commit') return 'push';
  return typing ? 'replace' : 'push';
}
