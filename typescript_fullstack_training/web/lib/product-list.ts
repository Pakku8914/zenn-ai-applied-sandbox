// 練習問題6・7 の解答。一覧ページと generateMetadata が同じ計算を必要とするため、
// クエリ文字列の解釈から表示分の切り出しまでを1つの関数にまとめている。

import { PRODUCTS, findCategoryBySlug } from '@/lib/products';
import {
  calcPagination,
  filterAndSortProducts,
  parseKeyword,
  parseProductQuery,
  searchProducts,
  type RawSearchParams,
} from '@/lib/product-query';

/** 一覧ページが必要とするものを、クエリ文字列からまとめて組み立てる */
export function selectProductList(raw: RawSearchParams) {
  const query = parseProductQuery(raw);
  const keyword = parseKeyword(raw['q']);
  const category = query.categorySlug === null ? undefined : findCategoryBySlug(query.categorySlug);
  const searched = searchProducts(PRODUCTS, keyword);
  const selected = filterAndSortProducts(searched, category?.id ?? null, query.sort);
  const pagination = calcPagination(selected.length, query.page);

  return {
    query,
    keyword,
    category,
    selected,
    pagination,
    visible: selected.slice(pagination.skip, pagination.skip + pagination.take),
  };
}
