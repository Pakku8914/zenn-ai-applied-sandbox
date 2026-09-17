import type { Metadata } from 'next';
import Link from 'next/link';
import { findCartItems } from '@/lib/cart-repository';
import { findProductSummaryPage } from '@/lib/product-repository';
import { buildPaymentSummary, calcLineTotal } from '@/lib/pricing';
import { formatYen } from '@/lib/format';
import { CartSummary } from '@/components/CartSummary';
import { AddToCartForm } from '@/components/AddToCartForm';
import { QuantityForm } from '@/components/QuantityForm';
import { RemoveItemForm } from '@/components/RemoveItemForm';
// 練習問題4で作るお届け先フォーム
import { CustomerForm } from '@/components/CustomerForm';
import { requireSessionUser } from '@/lib/session';

export const metadata: Metadata = {
  title: 'カート',
  description: '選んだ商品と支払総額を確認します。',
};

// カートは利用者ごとに違う内容なので、ビルド時に固定の HTML にしてはいけない。
export const dynamic = 'force-dynamic';

// このページはサーバーコンポーネント。データベースを読むのはこちら側の仕事で、
// 送信ボタンを持つ部分（フォーム）だけをクライアントコンポーネントに任せている。
export default async function CartPage() {
  // 最終プロジェクトで固定の DEMO_USER_ID をやめ、セッションから取るようにした。
  // カートは cart_items の user_id で分かれているので、ここが固定値だと全員が
  // 同じカートを共有してしまう
  const user = await requireSessionUser('/cart');

  // 互いに独立した2つの問い合わせなので並行に実行する（セッション17）
  const [items, catalog] = await Promise.all([
    findCartItems(user.id),
    findProductSummaryPage({
      categoryId: null,
      keyword: '',
      sort: 'price-asc',
      page: 1,
      pageSize: 10,
    }),
  ]);

  // cart_items の行は { product, quantity } を含むので、そのまま金額計算に渡せる
  const summary = buildPaymentSummary(items);

  return (
    <div>
      <h1>カート</h1>
      <p>
        <Link href="/products">商品一覧に戻る</Link>
      </p>

      <h2>商品を選ぶ</h2>
      <ul>
        {catalog.items.map((product) => (
          <li key={product.id}>
            {`${product.name}（${formatYen(product.price)}） `}
            <AddToCartForm
              productId={product.id}
              productName={product.name}
              stock={product.stock}
            />
          </li>
        ))}
      </ul>

      <h2>{`カートの中身（${items.length}明細）`}</h2>
      {items.length === 0 ? (
        // 空のカートで「送料500円・支払総額500円」と出さない（セッション19で見つけた穴）
        <p>カートは空です。上の一覧から商品を選んでください。</p>
      ) : (
        <>
          <ul>
            {items.map((item) => (
              <li key={item.id}>
                {`${item.product.name} 小計 ${formatYen(
                  calcLineTotal(item.product.price, item.quantity)
                )} `}
                <QuantityForm
                  productId={item.productId}
                  quantity={item.quantity}
                  stock={item.product.stock}
                />
                <RemoveItemForm productId={item.productId} />
              </li>
            ))}
          </ul>
          <CartSummary summary={summary} />
          <CustomerForm />
          <p>
            <Link href="/checkout">ご注文の確認へ進む</Link>
          </p>
        </>
      )}
    </div>
  );
}
