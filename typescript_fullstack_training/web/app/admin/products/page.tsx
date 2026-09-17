import type { Metadata } from 'next';
import Link from 'next/link';
import { findAllCategories, findProductDetailPage } from '@/lib/product-repository';
import { describeStockFailure, judgeReservation } from '@/lib/stock';
import { formatYen } from '@/lib/format';
import { DeleteProductForm } from '@/components/DeleteProductForm';
import { ProductEditorForm } from '@/components/ProductEditorForm';

// 毎回データベースの現在値を見る画面なので、ビルド時に固定の HTML にしない。
// 管理画面はキャッシュ付きの関数（findProductDetailPageCached）を使わない。
// 「いま在庫が何点か」を見るための画面で、1分古い値では役に立たないためである。
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: '商品マスタ（管理）' };

export default async function AdminProductsPage() {
  // カテゴリ一覧と商品一覧は互いに独立しているので並行に問い合わせる（セッション17）。
  const [categories, page] = await Promise.all([
    findAllCategories(),
    findProductDetailPage({
      categoryId: null,
      keyword: '',
      sort: 'price-asc',
      page: 1,
      pageSize: 50,
    }),
  ]);

  // 在庫金額（価格 × 在庫数）の合計。セッション10で確認した 54170 円と一致する。
  const totalStockValue = page.items.reduce(
    (sum, product) => sum + product.price * product.stock,
    0
  );

  return (
    <div>
      <h1>商品マスタ（管理）</h1>

      <p>{`カテゴリ ${categories.length}件 / 商品 ${page.totalCount}件 / 在庫金額 ${formatYen(totalStockValue)}`}</p>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>商品名</th>
            <th>カテゴリ</th>
            <th>価格</th>
            <th>在庫</th>
            <th>状態</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((product) => {
            // 「いま1点買えるか」の判定。純粋な関数なので画面でもAPIでも同じ結果になる
            const availability = judgeReservation(product.id, product.stock, 1);

            return (
              <tr key={product.id}>
                <td>{product.id}</td>
                <td>{product.name}</td>
                {/* include: { category: true } で一緒に取ってあるので、ここで追加の問い合わせは起きない */}
                <td>{product.category.name}</td>
                <td>{formatYen(product.price)}</td>
                <td>{product.stock}</td>
                <td>
                  {availability.kind === 'ok' ? '販売中' : describeStockFailure(availability.error)}
                </td>
                <td>
                  <Link href={`/admin/products/${product.id}/edit`}>編集</Link>
                  <DeleteProductForm productId={product.id} productName={product.name} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>商品を登録する</h2>
      <ProductEditorForm mode="create" categories={categories} />

      <p>
        <Link href="/admin/orders">注文一覧を見る</Link>{' '}
        <Link href="/products">お客さま向けの一覧を見る</Link>
      </p>
    </div>
  );
}
