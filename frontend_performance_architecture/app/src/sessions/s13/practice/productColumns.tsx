import type { Product } from '../../../data/products';
import { formatPrice } from './formatters';
import type { Column } from './SimpleTable';

/**
 * 画面固有：商品の列の定義。satisfies で「どれも Column<Product> であること」を確かめつつ、
 * どの列名があるか（name / price / category）は型に残す。
 */
export const productColumns = {
  name: { header: '商品名', render: (p) => p.name },
  price: { header: '価格', render: (p) => formatPrice(p.price), align: 'right' },
  category: { header: 'カテゴリ', render: (p) => p.category },
} satisfies Record<string, Column<Product>>;
