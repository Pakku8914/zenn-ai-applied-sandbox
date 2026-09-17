// カテゴリタブだけを担当する区画（セッション27）。
//
// page.tsx から <Suspense> で包んで使う。データの取得をこの中に閉じ込めることで、
// 「タブが届くのを待っているあいだ、商品一覧の取得は止まらない」状態になる。

import { CategoryTabs } from '@/components/CategoryTabs';
import { findAllCategoriesCached } from '@/lib/product-repository';

type CategorySectionProps = {
  activeSlug: string | null;
};

export async function CategorySection({ activeSlug }: CategorySectionProps) {
  // キャッシュ付きの入口を使う。カテゴリは滅多に変わらないので寿命を長くしてある
  const categories = await findAllCategoriesCached();

  return <CategoryTabs categories={categories} activeSlug={activeSlug} />;
}
