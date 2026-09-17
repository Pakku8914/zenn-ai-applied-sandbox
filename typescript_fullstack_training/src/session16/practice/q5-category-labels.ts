// 問題5：satisfies でマスタデータのキーを守る。
import { products } from '../shop-data';

export type CategorySlug = 'bath-body' | 'kitchen' | 'fabric';

/** 表示順を固定した slug の一覧 */
export const CATEGORY_SLUGS = [
  'bath-body',
  'kitchen',
  'fabric',
] as const satisfies readonly CategorySlug[];

/** カテゴリの表示名。satisfies でキーの網羅を検査し、値はリテラル型のまま保つ */
export const CATEGORY_LABEL = {
  'bath-body': 'バス・ボディケア',
  kitchen: 'キッチン雑貨',
  fabric: 'ファブリック',
} as const satisfies Record<CategorySlug, string>;

/** categoryId から slug へ。存在しない id では undefined になる */
const SLUG_BY_CATEGORY_ID: Record<number, CategorySlug> = {
  1: 'bath-body',
  2: 'kitchen',
  3: 'fabric',
};

export function toCategorySlug(categoryId: number): CategorySlug | undefined {
  return SLUG_BY_CATEGORY_ID[categoryId];
}

export function categoryLabelOf(categoryId: number): string {
  const slug = toCategorySlug(categoryId);
  return slug === undefined ? '(不明なカテゴリ)' : CATEGORY_LABEL[slug];
}

export function formatCategoryReport(): string {
  const lines = CATEGORY_SLUGS.map((slug) => {
    const names = products
      .filter((product) => toCategorySlug(product.categoryId) === slug)
      .map((product) => product.name);
    return `${CATEGORY_LABEL[slug]}: ${names.join(' / ')}`;
  });

  lines.push(`categoryId=9: ${categoryLabelOf(9)}`);
  return lines.join('\n');
}
