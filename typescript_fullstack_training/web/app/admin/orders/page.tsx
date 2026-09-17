import type { Metadata } from 'next';
import Link from 'next/link';
import { AccessDenied } from '@/components/AccessDenied';
import { judgeAdminAccess, statusForFailure } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';
import { findAllOrderList } from '@/lib/order-repository';
import { describeOrderStatus, describePaymentStatus } from '@/lib/order-status';
import { formatYen } from '@/lib/format';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: '注文一覧（管理）' };

export default async function AdminOrdersPage() {
  // レイアウトでも確かめているが、ページでも確かめる。
  // findAllOrderList は userId で絞らない関数なので、呼ぶ前の確認を省けない
  const user = await getSessionUser();
  const failure = judgeAdminAccess(user);

  if (failure !== null) {
    return (
      <AccessDenied
        status={statusForFailure(failure)}
        description="管理者だけが開けるページです。"
      />
    );
  }

  const orders = await findAllOrderList();

  return (
    <div>
      <h1>注文一覧（管理）</h1>

      <p>{`直近 ${orders.length}件`}</p>

      {orders.length === 0 ? (
        <p>まだ注文はありません。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>注文</th>
              <th>お客さま</th>
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
                <td>{`#${order.id}`}</td>
                <td>{order.userEmail}</td>
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
        <Link href="/admin/products">商品マスタに戻る</Link>
      </p>
    </div>
  );
}
