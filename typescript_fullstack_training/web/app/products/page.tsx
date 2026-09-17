import { Suspense } from 'react';
import { CategorySection } from '@/app/products/CategorySection';
import { ProductListSection } from '@/app/products/ProductListSection';
import { CategoryTabsSkeleton } from '@/components/CategoryTabsSkeleton';
import { ProductListSkeleton } from '@/components/ProductListSkeleton';
import {
  PAGE_SIZE,
  parseKeyword,
  parseProductQuery,
  type RawSearchParams,
} from '@/lib/product-query';

// このページは searchParams（リクエストごとに変わる値）を読むので、
// 何を書いても動的レンダリングになる。それを宣言として明示しておく。
// キャッシュを効かせているのはページ単位ではなく、データ単位（lib/product-repository.ts）。
export const dynamic = 'force-dynamic';

// searchParams は Next.js 15 から Promise なので、async 関数にして await で受け取る。
export default async function ProductListPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  // ここは軽い処理だけ。重い問い合わせは Suspense の内側に押し込む
  const raw = await searchParams;
  const query = parseProductQuery(raw);
  const keyword = parseKeyword(raw['q']);

  // 条件が変わったら境界を作り直す。key が変わると、
  // 新しい中身を待つあいだにもう一度スケルトンが出る（前の結果が残らない）
  const boundaryKey = `${query.categorySlug ?? 'all'}:${keyword}:${query.sort}:${query.page}`;

  return (
    <div>
      <h1>商品一覧</h1>

      {/* 境界は「待たせたい単位」で分ける。タブと一覧は別々に届く */}
      <Suspense fallback={<CategoryTabsSkeleton />}>
        <CategorySection activeSlug={query.categorySlug} />
      </Suspense>

      <Suspense key={boundaryKey} fallback={<ProductListSkeleton rows={PAGE_SIZE} />}>
        <ProductListSection query={query} keyword={keyword} />
      </Suspense>
    </div>
  );
}
