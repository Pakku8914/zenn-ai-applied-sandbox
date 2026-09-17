// URL から受け取った文字列を、画面が使える値に変換する純粋な関数だけを集めたモジュール。
// React も Next.js も使っていないので、この中身は sandbox/src/session21/verify.ts で検証できる。

import { findCategoryBySlug, type Product } from './products';

/** 1ページに表示する件数 */
export const PAGE_SIZE = 3;

/** 並べ替えの種類。文字列として URL に載るのでリテラル型のユニオンで固定する */
export type SortKey = 'price-asc' | 'price-desc' | 'name-asc';

const SORT_KEYS = ['price-asc', 'price-desc', 'name-asc'] as const;

/** 既定の並べ替え。指定が無い・不正なときはこれに落とす */
export const DEFAULT_SORT: SortKey = 'price-asc';

/** Next.js の searchParams が渡してくる生の形。同じキーが2回来ると配列になる */
export type RawSearchParams = { [key: string]: string | string[] | undefined };

/** 画面が実際に使う、検証済みの絞り込み条件 */
export type ProductQuery = {
  categorySlug: string | null;
  sort: SortKey;
  page: number;
};

/** ページ送りの計算結果 */
export type Pagination = {
  page: number;
  totalPages: number;
  skip: number;
  take: number;
};

/**
 * 動的ルートの params で受け取った文字列を商品 ID に変換する。
 * 数字だけで、先頭が 0 でなく、安全に扱える整数のときだけ数値を返す。
 */
export function parseProductId(raw: string): number | null {
  if (!/^[1-9][0-9]*$/.test(raw)) {
    return null;
  }

  const id = Number(raw);

  return Number.isSafeInteger(id) ? id : null;
}

/** 同じキーが複数回来たときは最初の値だけを使う */
function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function isSortKey(value: string): value is SortKey {
  return (SORT_KEYS as readonly string[]).includes(value);
}

function parseCategorySlug(value: string | string[] | undefined): string | null {
  const slug = firstValue(value);

  if (slug === undefined || findCategoryBySlug(slug) === undefined) {
    return null;
  }

  return slug;
}

function parseSort(value: string | string[] | undefined): SortKey {
  const sort = firstValue(value);

  return sort !== undefined && isSortKey(sort) ? sort : DEFAULT_SORT;
}

function parsePage(value: string | string[] | undefined): number {
  const page = Number(firstValue(value) ?? '1');

  return Number.isInteger(page) && page >= 1 ? page : 1;
}

/** クエリ文字列を検証済みの条件に変換する。不正な値はすべて既定値に落とす */
export function parseProductQuery(raw: RawSearchParams): ProductQuery {
  return {
    categorySlug: parseCategorySlug(raw['category']),
    sort: parseSort(raw['sort']),
    page: parsePage(raw['page']),
  };
}

/** 総件数と希望のページ番号から、実際に表示するページと切り出し位置を決める */
export function calcPagination(
  totalCount: number,
  requestedPage: number,
  pageSize: number = PAGE_SIZE
): Pagination {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const page = Math.min(Math.max(requestedPage, 1), totalPages);

  return { page, totalPages, skip: (page - 1) * pageSize, take: pageSize };
}

function compareBy(sort: SortKey): (a: Product, b: Product) => number {
  switch (sort) {
    case 'price-asc':
      return (a, b) => a.price - b.price;
    case 'price-desc':
      return (a, b) => b.price - a.price;
    case 'name-asc':
      return (a, b) => a.name.localeCompare(b.name, 'ja');
    default: {
      // ユニオンに新しい並べ替えを足したら、ここで型エラーになって気づける
      const unreachable: never = sort;

      throw new Error(`未知の並べ替えです: ${String(unreachable)}`);
    }
  }
}

/** カテゴリで絞り、並べ替えた新しい配列を返す（元の配列は変更しない） */
export function filterAndSortProducts(
  products: readonly Product[],
  categoryId: number | null,
  sort: SortKey
): Product[] {
  const filtered =
    categoryId === null
      ? [...products]
      : products.filter((product) => product.categoryId === categoryId);

  return filtered.sort(compareBy(sort));
}

/** いまの絞り込みを保ったまま、ページ番号だけ差し替えたリンク先を作る */
export function buildProductsHref(query: ProductQuery, page: number): string {
  const params = new URLSearchParams();

  if (query.categorySlug !== null) {
    params.set('category', query.categorySlug);
  }
  if (query.sort !== DEFAULT_SORT) {
    params.set('sort', query.sort);
  }
  if (page > 1) {
    params.set('page', String(page));
  }

  const queryString = params.toString();

  return queryString === '' ? '/products' : `/products?${queryString}`;
}

/** 検索語の最大文字数。長すぎる入力で表示が崩れたり無駄な処理が増えるのを防ぐため */
export const MAX_KEYWORD_LENGTH = 50;

export function parseKeyword(value: string | string[] | undefined): string {
  return (firstValue(value) ?? '').trim().slice(0, MAX_KEYWORD_LENGTH);
}

/** 商品名の部分一致で絞る。空のキーワードは「検索していない」扱い */
export function searchProducts(products: readonly Product[], keyword: string): Product[] {
  if (keyword === '') {
    return [...products];
  }

  const lowered = keyword.toLowerCase();

  return products.filter((product) => product.name.toLowerCase().includes(lowered));
}

export function buildSearchTitle(keyword: string, count: number): string {
  return keyword === '' ? '商品一覧' : `「${keyword}」の検索結果（${count}件）`;
}
