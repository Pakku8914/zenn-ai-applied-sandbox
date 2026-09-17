// 注文（orders / order_items / payments）への読み書きをまとめる場所（最終プロジェクト）。
//
// セッション25 では app/orders/order-queries.ts に置いていたが、注文は
// 画面・API・Webhook・管理画面の4か所から触るようになったので lib/ に引き上げた。
// 「どんな SQL が飛ぶか」と「どこで userId を条件に入れているか」を1か所に閉じ込める。
//
// 設計の約束：お客さま向けの関数は必ず userId を引数に取る。
// 渡さないと型エラーになるので、認可の確認を忘れられない（セッション25）。

import { prisma } from '@/lib/db';
import { parseOrderStatus, type OrderStatus } from '@/lib/order-status';

/** 注文明細1行。商品名は表示用に結合して持つ */
export type OrderItemRow = {
  id: number;
  productId: number;
  productName: string;
  quantity: number;
  /** 注文した時点の単価。商品の価格が変わってもここは動かない */
  unitPrice: number;
};

export type OrderPaymentRow = {
  status: string;
  amount: number;
  idempotencyKey: string;
};

/** 一覧の1行。明細の件数と決済の状態だけを添える（明細そのものは詳細で見せる） */
export type OrderListRow = {
  id: number;
  userId: number;
  status: OrderStatus;
  totalAmount: number;
  createdAt: Date;
  itemCount: number;
  paymentStatus: string | null;
};

/** 詳細。明細と決済を含む */
export type OrderDetailRow = {
  id: number;
  userId: number;
  status: OrderStatus;
  totalAmount: number;
  createdAt: Date;
  items: OrderItemRow[];
  payment: OrderPaymentRow | null;
};

/** 管理画面の一覧。誰の注文かを添える */
export type AdminOrderRow = OrderListRow & { userEmail: string };

/** その利用者の注文を新しい順に。件数は _count で数えるので明細は取らない */
export async function findOrderListForUser(userId: number): Promise<OrderListRow[]> {
  const rows = await prisma.order.findMany({
    where: { userId },
    orderBy: { createdAt: 'desc' },
    select: {
      id: true,
      userId: true,
      status: true,
      totalAmount: true,
      createdAt: true,
      // 明細を全部取ってから数えると、注文が増えるほど転送量が増える
      _count: { select: { items: true } },
      payment: { select: { status: true } },
    },
  });

  return rows.map((row) => ({
    id: row.id,
    userId: row.userId,
    status: parseOrderStatus(row.status),
    totalAmount: row.totalAmount,
    createdAt: row.createdAt,
    itemCount: row._count.items,
    paymentStatus: row.payment === null ? null : row.payment.status,
  }));
}

/**
 * 注文1件（明細と決済つき）。
 * 「自分のものか」を問い合わせの条件に入れる。取ってきてから if で確かめる形にしない。
 * 明細と決済は1回の問い合わせで一緒に取るので、N+1 は起きない（セッション23）。
 */
export async function findOrderDetailForUser(
  orderId: number,
  userId: number
): Promise<OrderDetailRow | undefined> {
  const row = await prisma.order.findFirst({
    where: { id: orderId, userId },
    select: {
      id: true,
      userId: true,
      status: true,
      totalAmount: true,
      createdAt: true,
      items: {
        orderBy: { id: 'asc' },
        select: {
          id: true,
          productId: true,
          quantity: true,
          unitPrice: true,
          product: { select: { name: true } },
        },
      },
      payment: { select: { status: true, amount: true, idempotencyKey: true } },
    },
  });

  if (row === null) {
    return undefined;
  }

  return {
    id: row.id,
    userId: row.userId,
    status: parseOrderStatus(row.status),
    totalAmount: row.totalAmount,
    createdAt: row.createdAt,
    items: row.items.map((item) => ({
      id: item.id,
      productId: item.productId,
      productName: item.product.name,
      quantity: item.quantity,
      unitPrice: item.unitPrice,
    })),
    payment: row.payment,
  };
}

/**
 * 全員の注文（管理画面用）。
 * こちらは userId で絞らない。だから呼ぶ場所を管理画面に限り、
 * 呼ぶ前に必ず canAccessAdmin で確かめる（お客さま向けの関数と混ぜない）。
 */
export async function findAllOrderList(limit: number = 50): Promise<AdminOrderRow[]> {
  const rows = await prisma.order.findMany({
    orderBy: { createdAt: 'desc' },
    take: limit,
    select: {
      id: true,
      userId: true,
      status: true,
      totalAmount: true,
      createdAt: true,
      _count: { select: { items: true } },
      payment: { select: { status: true } },
      user: { select: { email: true } },
    },
  });

  return rows.map((row) => ({
    id: row.id,
    userId: row.userId,
    status: parseOrderStatus(row.status),
    totalAmount: row.totalAmount,
    createdAt: row.createdAt,
    itemCount: row._count.items,
    paymentStatus: row.payment === null ? null : row.payment.status,
    userEmail: row.user.email,
  }));
}

/**
 * ステータスを条件付きで進める。
 *
 * where に「いまの状態」を入れるのが要点である。update ではなく updateMany を
 * 使うのは、条件に合う行が無いときに例外ではなく count: 0 が返ってほしいため。
 * これで「2回適用されない」ことをデータベース1回の往復で保証できる。
 */
export async function advanceOrderStatus(
  orderId: number,
  from: OrderStatus,
  to: OrderStatus
): Promise<boolean> {
  const updated = await prisma.order.updateMany({
    where: { id: orderId, status: from },
    data: { status: to },
  });

  return updated.count === 1;
}

/** 在庫を戻すために必要な最小限（どの商品を何点引き当てたか） */
export async function findOrderLinesForRelease(
  orderId: number
): Promise<{ productId: number; quantity: number }[]> {
  return prisma.orderItem.findMany({
    where: { orderId },
    select: { productId: true, quantity: true },
    orderBy: { id: 'asc' },
  });
}

/** pending のまま放置された注文の ID を集める（補償処理の掃除で使う） */
export async function findStalePendingOrderIds(before: Date): Promise<number[]> {
  const rows = await prisma.order.findMany({
    where: { status: 'pending', createdAt: { lt: before } },
    select: { id: true },
    orderBy: { id: 'asc' },
  });

  return rows.map((row) => row.id);
}

/** 注文の状態と金額だけを引く（Webhook の照合に使う） */
export async function findOrderForSettlement(
  orderId: number
): Promise<{ id: number; status: OrderStatus; totalAmount: number } | undefined> {
  const row = await prisma.order.findUnique({
    where: { id: orderId },
    select: { id: true, status: true, totalAmount: true },
  });

  if (row === null) {
    return undefined;
  }

  return { id: row.id, status: parseOrderStatus(row.status), totalAmount: row.totalAmount };
}
