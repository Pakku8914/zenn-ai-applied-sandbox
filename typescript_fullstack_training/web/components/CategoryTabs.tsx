// カテゴリの切り替えリンク（練習問題3）。
// 選択中のカテゴリはリンクにせず文字だけを出す＝条件付きレンダリング。
// key には配列の添字ではなく、値そのものが持つ識別子（slug）を使う。

import Link from 'next/link';
import type { Category } from '@/lib/products';

type CategoryTabsProps = {
  categories: readonly Category[];
  /** いま選ばれている slug。未選択（すべて）なら null */
  activeSlug: string | null;
};

export function CategoryTabs({ categories, activeSlug }: CategoryTabsProps) {
  return (
    <nav>
      <ul>
        <li>{activeSlug === null ? <strong>すべて</strong> : <Link href="/products">すべて</Link>}</li>
        {categories.map((category) => (
          <li key={category.slug}>
            {category.slug === activeSlug ? (
              <strong>{category.name}</strong>
            ) : (
              <Link href={`/products?category=${category.slug}`}>{category.name}</Link>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
