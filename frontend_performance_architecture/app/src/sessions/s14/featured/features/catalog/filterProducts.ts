import type { Product } from '../../../../../data/products';

/** catalog の内部でだけ使う絞り込み。外からは import させない（index.ts から公開しない） */
export function filterProducts(items: readonly Product[], keyword: string): readonly Product[] {
  return keyword === '' ? items : items.filter((p) => p.name.includes(keyword));
}
