// 商品1件の表示を担当する部品。props は「セッション11で決めた Product 型そのまま」1つだけ。
// サーバーコンポーネントだが、中にクライアントコンポーネント（AddToCartButton）を置ける。

import Link from 'next/link';
import type { Product } from '@/lib/products';
import { formatYen, stockLabel } from '@/lib/format';
import { AddToCartButton } from '@/components/AddToCartButton';

type ProductCardProps = {
  product: Product;
};

export function ProductCard({ product }: ProductCardProps) {
  const soldOut = product.stock === 0;

  return (
    <li>
      <Link href={`/products/${product.id}`}>{product.name}</Link>
      {` ${formatYen(product.price)}（税抜） / ${stockLabel(product.stock)} `}
      <AddToCartButton productName={product.name} soldOut={soldOut} />
    </li>
  );
}
