// キャッシュの「タグ」と「キー」を組み立てる場所（セッション27）。
//
// ここには Next.js に依存しない純粋な関数だけを置く。
// タグを文字列リテラルで散らかすと、無効化のときに1か所でも書き漏らして
// 「更新したのに一覧が変わらない」が起きる。名前を作る場所を1つに閉じ込める。
//
// 同じ実装を src/session27/verify.ts で検証している。

import type { SortKey } from '@/lib/product-query';

/** 商品の一覧・件数など「商品全体」に関わるキャッシュのタグ */
export const PRODUCTS_TAG = 'products';

/** カテゴリ一覧に関わるキャッシュのタグ */
export const CATEGORIES_TAG = 'categories';

/** 商品1件だけに関わるタグ。詳細ページのキャッシュを狙って捨てるために使う */
export function productTag(productId: number): string {
  return `product-${productId}`;
}

/** カテゴリ1つに関わるタグ。そのカテゴリで絞った一覧を狙って捨てるために使う */
export function categoryTag(slug: string): string {
  return `category-${slug}`;
}

/** 商品を1件更新したときの状況 */
export type ProductUpdateTarget = {
  productId: number;
  /** 更新後のカテゴリの slug */
  categorySlug: string;
  /** カテゴリを移動した場合は移動前の slug。移動していなければ null */
  previousCategorySlug: string | null;
};

/**
 * 商品を1件更新したときに捨てるべきタグの一覧。
 * カテゴリを移動した場合は「移動先」と「移動元」の両方を捨てないと、
 * 移動元のカテゴリ一覧にその商品が残り続ける。
 */
export function tagsForProductUpdate(target: ProductUpdateTarget): string[] {
  const tags = [PRODUCTS_TAG, productTag(target.productId), categoryTag(target.categorySlug)];

  if (target.previousCategorySlug !== null) {
    tags.push(categoryTag(target.previousCategorySlug));
  }

  // 同じタグを2回捨てても害は無いが、ログが読みにくくなるので重複は取り除く
  return [...new Set(tags)];
}

/** 一覧の問い合わせ条件（キャッシュキーの材料） */
export type ProductListCacheInput = {
  categoryId: number | null;
  keyword: string;
  sort: SortKey;
  page: number;
};

/**
 * 一覧の問い合わせ条件から、決定的な（同じ条件なら必ず同じ）キーを作る。
 *
 * オブジェクトをそのまま JSON にすると「書いた順番」でキーが変わってしまう。
 * 必要なフィールドを決まった順番で読み出すことで、順番に左右されないキーになる。
 * キーワードは前後の空白と大文字小文字の違いを吸収してから使う。
 */
export function buildProductListCacheKey(input: ProductListCacheInput): string {
  const category = input.categoryId === null ? 'all' : String(input.categoryId);
  const keyword = input.keyword.trim().toLowerCase();

  return [
    'products',
    `category=${category}`,
    `keyword=${keyword}`,
    `sort=${input.sort}`,
    `page=${input.page}`,
  ].join(':');
}
