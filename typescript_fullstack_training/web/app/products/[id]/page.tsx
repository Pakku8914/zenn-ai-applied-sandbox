import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { findCategoryById, findProductById } from '@/lib/products';
import { parseProductId } from '@/lib/product-query';

// params も Next.js 15 から Promise。ページと generateMetadata で同じ形を使うので型に名前を付ける。
type ProductDetailProps = {
  params: Promise<{ id: string }>;
};

/** URL の :id から商品を1件取り出す。ID の形が不正でも「見つからない」として扱う */
function loadProduct(rawId: string) {
  const productId = parseProductId(rawId);

  return productId === null ? undefined : findProductById(productId);
}

// このページだけのタイトルと説明。layout.tsx の template と組み合わさって
// 「マグカップ | ミニ雑貨ショップ」になる。
export async function generateMetadata({ params }: ProductDetailProps): Promise<Metadata> {
  const { id } = await params;
  const product = loadProduct(id);

  if (product === undefined) {
    return { title: '商品が見つかりません' };
  }

  return { title: product.name, description: product.description };
}

export default async function ProductDetailPage({ params }: ProductDetailProps) {
  const { id } = await params;
  const product = loadProduct(id);

  if (product === undefined) {
    // notFound() の戻り値の型は never。これより下は実行されないことが型でも分かる。
    notFound();
  }

  const category = findCategoryById(product.categoryId);

  return (
    <article>
      <h1>{product.name}</h1>
      <p>{product.description}</p>

      <p>{`${product.price}円（税抜）`}</p>
      <p>{product.stock === 0 ? '在庫切れ' : `在庫 ${product.stock}点`}</p>
      <p>{category === undefined ? '未分類' : category.name}</p>

      <p>
        <Link href="/products">商品一覧に戻る</Link>
      </p>
    </article>
  );
}
