import type { Metadata } from 'next';
import Link from 'next/link';
import { findCartItems } from '@/lib/cart-repository';
import { buildPaymentSummary, calcLineTotal } from '@/lib/pricing';
import { formatYen } from '@/lib/format';
import { CartSummary } from '@/components/CartSummary';
import { PlaceOrderForm } from '@/components/PlaceOrderForm';
import { requireSessionUser } from '@/lib/session';

// ログインしている人ごとに内容が変わる画面なので、ビルド時に固定の HTML にしない。
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'ご注文の確認' };

export default async function CheckoutPage() {
  const user = await requireSessionUser('/checkout');
  const items = await findCartItems(user.id);
  const summary = buildPaymentSummary(items);

  if (items.length === 0) {
    return (
      <div>
        <h1>ご注文の確認</h1>
        <p>カートが空です。商品を選んでからお進みください。</p>
        <p>
          <Link href="/products">商品一覧へ</Link>
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1>ご注文の確認</h1>

      <p>{`${user.name} さんのご注文（${items.length}明細）`}</p>

      <table>
        <thead>
          <tr>
            <th>商品</th>
            <th>単価</th>
            <th>数量</th>
            <th>小計</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.product.name}</td>
              <td>{formatYen(item.product.price)}</td>
              <td>{`${item.quantity}点`}</td>
              <td>{formatYen(calcLineTotal(item.product.price, item.quantity))}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <CartSummary summary={summary} />

      <PlaceOrderForm payableAmountLabel={formatYen(summary.payableAmount)} />

      <p>
        <Link href="/cart">カートに戻って数量を変える</Link>
      </p>
    </div>
  );
}
