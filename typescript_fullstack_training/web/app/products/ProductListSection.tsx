// 商品一覧の中身だけを担当する区画（セッション27）。
//
// ページの中で一番時間がかかるのがここ。<Suspense> で包んで切り離しておくと、
// 見出しやタブは先に届き、この区画だけがスケルトンから差し替わる。

import Link from 'next/link';
import { ProductCard } from '@/components/ProductCard';
import { SectionCard } from '@/components/SectionCard';
import { buildProductListCacheKey } from '@/lib/cache-tags';
import { getLogger } from '@/lib/logger';
import { measure } from '@/lib/metrics';
import { buildProductsHref, type ProductQuery } from '@/lib/product-query';
import { findAllCategoriesCached, findProductDetailPageCached } from '@/lib/product-repository';

type ProductListSectionProps = {
  query: ProductQuery;
  keyword: string;
};

export async function ProductListSection({ query, keyword }: ProductListSectionProps) {
  const logger = getLogger();

  // カテゴリは3件しかなく、すでに1本のクエリで取ってキャッシュしてある。
  // slug からの引き当てのためにもう1本クエリを投げるのは無駄なので、メモリ上で探す。
  // findAllCategoriesCached は cache() で包んであるので、ここでの呼び出しは
  // CategorySection のぶんと合わせても1回しか実行されない。
  const categories = await findAllCategoriesCached();
  const category =
    query.categorySlug === null
      ? undefined
      : categories.find((item) => item.slug === query.categorySlug);

  const categoryId = category?.id ?? null;
  const cacheKey = buildProductListCacheKey({
    categoryId,
    keyword,
    sort: query.sort,
    page: query.page,
  });

  // 何ミリ秒かかったかを測る。キャッシュに当たった2回目以降は目に見えて短くなる
  const { durationMs, value } = await measure('findProductDetailPageCached', () =>
    findProductDetailPageCached({ categoryId, keyword, sort: query.sort, page: query.page })
  );
  const { items, totalCount, pagination } = value;

  logger.info('商品一覧を取得しました', {
    cacheKey,
    totalCount,
    itemCount: items.length,
    durationMs,
  });

  const heading = category === undefined ? 'すべての商品' : `${category.name}の商品`;

  return (
    <SectionCard title={heading}>
      <p>{`${totalCount}件（${pagination.page} / ${pagination.totalPages} ページ）`}</p>

      {items.length === 0 ? (
        <p>該当する商品がありません。</p>
      ) : (
        <ul>
          {items.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </ul>
      )}

      <p>
        {pagination.page > 1 ? (
          <Link href={buildProductsHref(query, pagination.page - 1)}>前へ</Link>
        ) : null}
        {pagination.page < pagination.totalPages ? (
          <Link href={buildProductsHref(query, pagination.page + 1)}>次へ</Link>
        ) : null}
      </p>
    </SectionCard>
  );
}
