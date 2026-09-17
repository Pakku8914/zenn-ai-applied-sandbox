import type { Metadata } from 'next';
import Link from 'next/link';
import { findOrderListForUser } from '@/lib/order-repository';
import { describeOrderStatus, describePaymentStatus } from '@/lib/order-status';
import { formatYen } from '@/lib/format';
import { requireSessionUser } from '@/lib/session';

// ログイン状態によって内容が変わる画面なので、ビルド時に固定の HTML にしない。
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: '注文履歴' };

export default async function OrdersPage() {
  // middleware も入口で弾いているが、ここでも必ず確かめる（多層防御）
  const user = await requireSessionUser('/orders');
  // 問い合わせに userId を渡す。渡さないと型エラーになるので、認可を忘れられない
  const orders = await findOrderListForUser(user.id);

  return (
    <div>
      <h1>注文履歴</h1>

      <p>{`${user.name} さんの注文：${orders.length}件`}</p>

      {orders.length === 0 ? (
        <p>まだ注文はありません。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>注文</th>
              <th>状態</th>
              <th>決済</th>
              <th>明細</th>
              <th>合計</th>
              <th>注文日時</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.id}>
                <td>
                  <Link href={`/orders/${order.id}`}>{`注文 #${order.id}`}</Link>
                </td>
                <td>{describeOrderStatus(order.status)}</td>
                <td>
                  {order.paymentStatus === null
                    ? '記録なし'
                    : describePaymentStatus(order.paymentStatus)}
                </td>
                <td>{`${order.itemCount}件`}</td>
                <td>{formatYen(order.totalAmount)}</td>
                <td>{order.createdAt.toISOString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p>
        <Link href="/products">買い物を続ける</Link>
      </p>
    </div>
  );
}
