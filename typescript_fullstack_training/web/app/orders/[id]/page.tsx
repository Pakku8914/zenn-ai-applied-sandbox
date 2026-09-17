import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { findOrderDetailForUser } from '@/lib/order-repository';
import { describeOrderStatus, describePaymentStatus } from '@/lib/order-status';
import { calcLineTotal } from '@/lib/pricing';
import { formatYen } from '@/lib/format';
import { requireSessionUser } from '@/lib/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: '注文の詳細' };

type OrderDetailProps = {
  params: Promise<{ id: string }>;
};

/** URL の :id は文字列。数値にできない値は「見つからない」として扱う */
function parseOrderId(raw: string): number | null {
  const id = Number(raw);

  return Number.isInteger(id) && id > 0 ? id : null;
}

export default async function OrderDetailPage({ params }: OrderDetailProps) {
  const { id } = await params;
  const user = await requireSessionUser(`/orders/${id}`);
  const orderId = parseOrderId(id);

  if (orderId === null) {
    notFound();
  }

  // 「自分の注文か」を問い合わせの条件に含める。
  // findUnique({ where: { id: orderId } }) だけでは他人の注文が取れてしまう
  const order = await findOrderDetailForUser(orderId, user.id);

  if (order === undefined) {
    // 他人の注文でも「無い」と同じ応答にする（その注文が存在することを漏らさない）
    notFound();
  }

  // 明細の単価は「注文した時点の価格」。いまの商品価格ではないので、
  // 商品マスタを引き直さず、この行の値だけで計算する
  const itemsTotal = order.items.reduce(
    (total, item) => total + calcLineTotal(item.unitPrice, item.quantity),
    0
  );

  return (
    <div>
      <h1>{`注文 #${order.id}`}</h1>

      <dl>
        <dt>状態</dt>
        <dd>{describeOrderStatus(order.status)}</dd>
        <dt>決済</dt>
        <dd>
          {order.payment === null ? '記録なし' : describePaymentStatus(order.payment.status)}
        </dd>
        <dt>支払総額</dt>
        <dd>{formatYen(order.totalAmount)}</dd>
        <dt>注文日時</dt>
        <dd>{order.createdAt.toISOString()}</dd>
      </dl>

      <h2>{`ご注文の内容（${order.items.length}明細）`}</h2>
      <table>
        <thead>
          <tr>
            <th>商品</th>
            <th>注文時の単価</th>
            <th>数量</th>
            <th>小計</th>
          </tr>
        </thead>
        <tbody>
          {order.items.map((item) => (
            <tr key={item.id}>
              <td>{item.productName}</td>
              <td>{formatYen(item.unitPrice)}</td>
              <td>{`${item.quantity}点`}</td>
              <td>{formatYen(calcLineTotal(item.unitPrice, item.quantity))}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p>{`商品小計（税抜）：${formatYen(itemsTotal)}`}</p>
      <p>{`支払総額（税・送料込）：${formatYen(order.totalAmount)}`}</p>

      {order.status === 'pending' ? (
        <p>
          お支払いの確認が取れていません。決済サービスからの連絡を待っています。
          しばらくしてもこの表示が変わらない場合、ご注文は自動的に取り消され、在庫はお戻しします。
        </p>
      ) : null}

      <p>
        <Link href="/orders">注文履歴に戻る</Link>
      </p>
    </div>
  );
}
