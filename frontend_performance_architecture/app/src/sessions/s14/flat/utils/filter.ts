import type { Product } from '../../../../data/products';

export function filterProducts(items: readonly Product[], keyword: string): readonly Product[] {
  return keyword === '' ? items : items.filter((p) => p.name.includes(keyword));
}
