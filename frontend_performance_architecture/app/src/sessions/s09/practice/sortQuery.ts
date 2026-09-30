import type { Product } from '../../../data/products';
import { parseCatalogQuery, toSearch, type CatalogQuery } from '../catalogQuery';

/** 練習問題2：並び順も URL に置く（`?sort=price-asc`） */
export const SORT_OPTIONS = ['id', 'price-asc', 'price-desc'] as const;
export type SortOption = (typeof SORT_OPTIONS)[number];
export const DEFAULT_SORT: SortOption = 'id';

export type SortedCatalogQuery = CatalogQuery & { sort: SortOption };

function isSort(value: string): value is SortOption {
  return (SORT_OPTIONS as readonly string[]).includes(value);
}

export function parseSortedQuery(search: string): SortedCatalogQuery {
  const raw = new URLSearchParams(search).get('sort') ?? DEFAULT_SORT;
  return { ...parseCatalogQuery(search), sort: isSort(raw) ? raw : DEFAULT_SORT };
}

export function toSortedSearch(query: SortedCatalogQuery): string {
  // 既存の変換を再利用し、sort を最後に足す（キーの順序を固定して、同じ状態を同じ URL にする）
  const params = new URLSearchParams(toSearch(query));
  if (query.sort !== DEFAULT_SORT) params.set('sort', query.sort);
  const search = params.toString();
  return search === '' ? '' : `?${search}`;
}

/** 元の配列は並べ替えない（products は全画面で共有している） */
export function sortProducts(items: readonly Product[], sort: SortOption): Product[] {
  const copy = [...items];
  if (sort === 'price-asc') return copy.sort((a, b) => a.price - b.price || a.id - b.id);
  if (sort === 'price-desc') return copy.sort((a, b) => b.price - a.price || a.id - b.id);
  return copy.sort((a, b) => a.id - b.id);
}
