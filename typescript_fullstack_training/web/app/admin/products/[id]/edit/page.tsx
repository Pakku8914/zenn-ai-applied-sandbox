import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { findAllCategories, findProductDraft } from '@/lib/product-repository';
import { ProductEditorForm } from '@/components/ProductEditorForm';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: '商品の編集（管理）' };

type EditProductPageProps = {
  params: Promise<{ id: string }>;
};

/** URL の :id は文字列。1以上の整数だけを通す */
function parseProductId(raw: string): number | null {
  return /^[1-9][0-9]{0,9}$/.test(raw) ? Number(raw) : null;
}

export default async function EditProductPage({ params }: EditProductPageProps) {
  // 管理者かどうかは app/admin/layout.tsx と各 Server Action で確かめている
  const { id } = await params;
  const productId = parseProductId(id);

  if (productId === null) {
    notFound();
  }

  const [categories, product] = await Promise.all([
    findAllCategories(),
    findProductDraft(productId),
  ]);

  if (product === null) {
    notFound();
  }

  return (
    <div>
      <h1>{`商品の編集：${product.name}`}</h1>

      <ProductEditorForm mode="edit" categories={categories} product={product} />

      <p>
        <Link href="/admin/products">商品マスタに戻る</Link>
      </p>
    </div>
  );
}
