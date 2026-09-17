// 注文の問い合わせ（セッション25）。
//
// どちらの関数も「誰のものか」を引数で必ず受け取る。こうしておくと、
// 呼ぶ側が userId を渡さないと型エラーになり、認可の確認を忘れられなくなる。
// （最終プロジェクトでは lib/order-repository.ts に移す）

import { prisma } from '@/lib/db';

/** 一覧・詳細で使う注文1件。status は 'pending' | 'paid' | 'shipped' | 'cancelled' の文字列 */
export type OrderSummary = {
  id: number;
  userId: number;
  status: string;
  totalAmount: number;
  createdAt: Date;
};

/** その利用者の注文を新しい順に */
export async function findOrdersForUser(userId: number): Promise<OrderSummary[]> {
  return prisma.order.findMany({
    where: { userId },
    orderBy: { createdAt: 'desc' },
    select: { id: true, userId: true, status: true, totalAmount: true, createdAt: true },
  });
}

/**
 * 注文1件。「自分のものか」の条件を where に入れる。
 * 取ってきてから if で確かめる形にしない（確かめ忘れが起きるため）。
 */
export async function findOrderForUser(
  orderId: number,
  userId: number
): Promise<OrderSummary | undefined> {
  const order = await prisma.order.findUnique({
    where: { id: orderId, userId },
    select: { id: true, userId: true, status: true, totalAmount: true, createdAt: true },
  });

  return order ?? undefined;
}
