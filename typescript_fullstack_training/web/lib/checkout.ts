// 注文確定・決済・補償処理（最終プロジェクト）。本書でいちばん難しい処理である。
//
// 順序がすべてを決める。次の順に固定してあり、この順を崩すと必ず穴が空く。
//
//   1. カートを読む。空なら失敗を返す
//   2. $transaction の中で、条件付き更新（stock: { gte: quantity }）で在庫を引き当て、
//      count が期待と違えばトランザクションを中断する（在庫不足）
//   3. 同じトランザクションの中で Order（pending）と OrderItem（そのときの単価）を作る
//   4. トランザクションの【外】で決済を呼ぶ（冪等キーは charge-<orderId>）
//   5. 成功 → paid ＋ Payment を作る／拒否 → 補償処理で在庫を戻して cancelled
//   6. カートを空にし、revalidateTag で表示を更新する
//
// なぜ決済をトランザクションの外でやるのか：
//   トランザクションを開いているあいだ、引き当てた商品の行にはロックがかかっている。
//   そこに「外部サービスの応答を待つ」を含めると、相手が3秒応答しなければ3秒間
//   その商品を誰も買えなくなる。相手が固まれば、こちらのデータベースも固まる。
//   外部呼び出しはトランザクションに入れない、が本書でもっとも重要な設計判断である。

import { revalidateTag } from 'next/cache';
import { prisma } from '@/lib/db';
import { PRODUCTS_TAG, productTag } from '@/lib/cache-tags';
import { findCartItems, type CartItemWithProduct } from '@/lib/cart-repository';
import { buildPaymentSummary } from '@/lib/pricing';
import { judgeQuantity, type Result } from '@/lib/stock';
import { getLogger } from '@/lib/logger';
import {
  buildIdempotencyKey,
  getPaymentGateway,
  type PaymentGateway,
  type PaymentResult,
} from '@/lib/payment/gateway';
import {
  advanceOrderStatus,
  findOrderForSettlement,
  findOrderLinesForRelease,
  findStalePendingOrderIds,
} from '@/lib/order-repository';
import {
  isProcessedEvent,
  markEventProcessed,
  type PaymentWebhookEvent,
  type WebhookOutcome,
} from '@/lib/payment/webhook';

/** 決済の失敗理由だけを取り出した型（セッション14のユーティリティ型） */
export type PaymentFailureReason = Extract<PaymentResult, { kind: 'failed' }>['reason'];

/** 注文確定の失敗。利用者が直せるものだけを並べる */
export type CheckoutFailure =
  | { kind: 'empty_cart' }
  | { kind: 'invalid_quantity'; productName: string; quantity: number }
  | { kind: 'stock_conflict'; productName: string }
  | { kind: 'payment_declined'; orderId: number; reason: PaymentFailureReason };

/** 注文が作れた場合の結果。支払いが確定したか、確認中かの2つ */
export type CheckoutSuccess =
  | { kind: 'paid'; orderId: number; payableAmount: number }
  | { kind: 'pending'; orderId: number };

export type CheckoutResult = Result<CheckoutSuccess, CheckoutFailure>;

/** 失敗を画面に出す日本語にする。網羅性は never で確かめる（セッション12） */
export function describeCheckoutFailure(failure: CheckoutFailure): string {
  switch (failure.kind) {
    case 'empty_cart':
      return 'カートが空です。商品を選んでからお進みください';
    case 'invalid_quantity':
      return `${failure.productName}の数量が正しくありません（${failure.quantity}点）`;
    case 'stock_conflict':
      return `${failure.productName}の在庫が足りませんでした。数量を見直してください`;
    case 'payment_declined':
      return 'お支払いを完了できませんでした。注文は取り消し、在庫はお戻ししました';
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * トランザクションを取り消すために投げる専用のエラー（セッション23で作ったものと同じ考え方）。
 * 対話型トランザクションは「値を返す＝確定」「例外を投げる＝取り消し」なので、
 * 途中でやめたいときは Result を返すのではなく投げる必要がある。
 */
class ReservationAbort extends Error {
  readonly productName: string;

  constructor(productName: string) {
    super(`在庫を引き当てられません: ${productName}`);
    this.name = 'ReservationAbort';
    this.productName = productName;
  }
}

/** pending のまま放置された注文を打ち切るまでの時間（ミリ秒）。15分 */
export const PENDING_ORDER_TTL_MS = 15 * 60 * 1000;

/** その注文はもう待つのをやめてよいか（純粋な判定。src/final/verify.ts で検証している） */
export function isStalePending(
  order: { status: string; createdAt: Date },
  now: number,
  ttlMs: number = PENDING_ORDER_TTL_MS
): boolean {
  return order.status === 'pending' && now - order.createdAt.getTime() >= ttlMs;
}

/** 商品に関するキャッシュを捨てる。在庫が動いたら一覧と詳細の両方が古くなる */
function revalidateStock(lines: readonly { productId: number }[]): void {
  revalidateTag(PRODUCTS_TAG);

  for (const line of lines) {
    revalidateTag(productTag(line.productId));
  }
}

/**
 * 在庫を引き当て、pending の注文と明細を1つのトランザクションで作る。
 *
 * updateMany の where に stock: { gte: quantity } を入れるのが要点である。
 * 「読んでから判断して書く」のではなく「条件に合う行だけを書く」ので、
 * 同時に2人が最後の1点を買おうとしても、成功するのは片方だけになる。
 */
async function reserveAndCreateOrder(
  userId: number,
  lines: readonly CartItemWithProduct[],
  payableAmount: number
): Promise<Result<{ orderId: number }, CheckoutFailure>> {
  try {
    const order = await prisma.$transaction(async (tx) => {
      for (const line of lines) {
        const reserved = await tx.product.updateMany({
          where: { id: line.productId, stock: { gte: line.quantity } },
          data: { stock: { decrement: line.quantity } },
        });

        // 更新できた行が1件でなければ、在庫が足りない（または商品が消えた）
        if (reserved.count !== 1) {
          throw new ReservationAbort(line.product.name);
        }
      }

      return tx.order.create({
        data: {
          userId,
          status: 'pending',
          totalAmount: payableAmount,
          items: {
            // 単価は「注文した時点の価格」を写して持つ。あとで値段を変えても
            // 過去の注文金額は動かない（セッション23で決めた設計）
            create: lines.map((line) => ({
              productId: line.productId,
              quantity: line.quantity,
              unitPrice: line.product.price,
            })),
          },
        },
        select: { id: true },
      });
    });

    return { kind: 'ok', value: { orderId: order.id } };
  } catch (error: unknown) {
    // 想定した失敗だけを Result に変換する。それ以外（接続断・設定ミス）は投げ直す
    if (error instanceof ReservationAbort) {
      return { kind: 'error', error: { kind: 'stock_conflict', productName: error.productName } };
    }

    throw error;
  }
}

/** 引き当てた在庫を戻す。1件ずつ update するが、まとめて1トランザクションで行う */
async function releaseStock(
  lines: readonly { productId: number; quantity: number }[]
): Promise<void> {
  if (lines.length === 0) {
    return;
  }

  await prisma.$transaction(
    lines.map((line) =>
      prisma.product.update({
        where: { id: line.productId },
        data: { stock: { increment: line.quantity } },
      })
    )
  );
}

/**
 * 支払い済みにして決済の記録を残す。
 * pending → paid の条件付き更新に失敗したら（＝誰かが先に決着させていたら）何もしない。
 */
export async function markOrderPaid(
  orderId: number,
  amount: number,
  idempotencyKey: string
): Promise<boolean> {
  const moved = await advanceOrderStatus(orderId, 'pending', 'paid');

  if (!moved) {
    return false;
  }

  // 冪等キーに @unique を張ってあるので、同じキーで2件目は作れない。
  // upsert にしておくと、pending で記録済みの行を成功に書き換えられる
  await prisma.payment.upsert({
    where: { idempotencyKey },
    update: { status: 'succeeded', amount },
    create: { orderId, idempotencyKey, status: 'succeeded', amount },
  });

  return true;
}

/** 応答が返ってこなかったときの記録。成功も失敗も分からない状態を残す */
async function recordPendingPayment(
  orderId: number,
  amount: number,
  idempotencyKey: string
): Promise<void> {
  await prisma.payment.upsert({
    where: { idempotencyKey },
    update: { status: 'pending', amount },
    create: { orderId, idempotencyKey, status: 'pending', amount },
  });
}

/**
 * 補償処理：注文を取り消し、引き当てた在庫を戻す。
 *
 * 先に「pending → cancelled」の条件付き更新を行い、1件更新できたときだけ在庫を戻す。
 * この順にしておくと、同じ注文に対して補償が2回走っても在庫は二重に戻らない
 * （2回目は count: 0 になり、そこで打ち切られる）。
 */
export async function cancelOrderAndReleaseStock(orderId: number): Promise<boolean> {
  const moved = await advanceOrderStatus(orderId, 'pending', 'cancelled');

  if (!moved) {
    return false;
  }

  const lines = await findOrderLinesForRelease(orderId);

  await releaseStock(lines);
  await prisma.payment.updateMany({ where: { orderId }, data: { status: 'failed' } });

  return true;
}

/** カートを空にする。注文明細に写し終えたあとに呼ぶ */
async function clearCart(userId: number): Promise<void> {
  await prisma.cartItem.deleteMany({ where: { userId } });
}

/**
 * 注文を確定する。
 * gateway を引数で受け取れるようにしてあるので、テストから偽物を差し込める。
 */
export async function placeOrder(
  userId: number,
  gateway: PaymentGateway = getPaymentGateway()
): Promise<CheckoutResult> {
  const logger = getLogger();

  // --- 1. カートを読む -----------------------------------------------------
  const lines = await findCartItems(userId);

  if (lines.length === 0) {
    return { kind: 'error', error: { kind: 'empty_cart' } };
  }

  // 数量の妥当性は在庫に触る前に確かめる（データベースを汚さない順序）
  for (const line of lines) {
    if (judgeQuantity(line.quantity).kind === 'error') {
      return {
        kind: 'error',
        error: {
          kind: 'invalid_quantity',
          productName: line.product.name,
          quantity: line.quantity,
        },
      };
    }
  }

  const summary = buildPaymentSummary(lines);

  // --- 2〜3. 在庫引当と注文作成（1つのトランザクション） -------------------
  const created = await reserveAndCreateOrder(userId, lines, summary.payableAmount);

  if (created.kind === 'error') {
    logger.warn('checkout.stock_conflict', { userId });

    return created;
  }

  const orderId = created.value.orderId;
  const idempotencyKey = buildIdempotencyKey(String(orderId));

  // --- 4. 決済（トランザクションの外） -------------------------------------
  const result = await gateway.charge({
    idempotencyKey,
    amount: summary.payableAmount,
    orderId: String(orderId),
  });

  // --- 5〜6. 結果に応じて確定・保留・補償 ----------------------------------
  switch (result.kind) {
    case 'succeeded': {
      await markOrderPaid(orderId, summary.payableAmount, idempotencyKey);
      await clearCart(userId);
      revalidateStock(lines);
      logger.info('checkout.paid', { orderId, amount: summary.payableAmount });

      return {
        kind: 'ok',
        value: { kind: 'paid', orderId, payableAmount: summary.payableAmount },
      };
    }
    case 'pending': {
      // 成功か失敗か分からない状態。ここで在庫を戻すと、あとで
      // 「成功していました」と通知が来たときに在庫がマイナスになる。
      // だから在庫は保持したまま Webhook を待ち、来なければ掃除の処理が取り消す
      await recordPendingPayment(orderId, summary.payableAmount, idempotencyKey);
      await clearCart(userId);
      revalidateStock(lines);
      logger.warn('checkout.payment_pending', { orderId });

      return { kind: 'ok', value: { kind: 'pending', orderId } };
    }
    case 'failed': {
      await cancelOrderAndReleaseStock(orderId);
      revalidateStock(lines);
      logger.warn('checkout.payment_declined', { orderId, reason: result.reason });

      return {
        kind: 'error',
        error: { kind: 'payment_declined', orderId, reason: result.reason },
      };
    }
    default: {
      const unreachable: never = result;

      throw new Error(`未知の決済結果です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * Webhook を1件適用する。
 *
 * 二重適用を防ぐ関所は2つある。
 *   1段目：受信済み eventId の記録（速いが、プロセス再起動で消える）
 *   2段目：条件付き更新（pending の行だけを更新する。これが本当の砦）
 */
export async function applyPaymentEvent(event: PaymentWebhookEvent): Promise<WebhookOutcome> {
  const logger = getLogger();

  if (isProcessedEvent(event.eventId)) {
    return { kind: 'duplicate', eventId: event.eventId };
  }

  const order = await findOrderForSettlement(event.orderId);

  if (order === undefined) {
    logger.warn('webhook.unknown_order', { orderId: event.orderId });

    return { kind: 'unknown_order', orderId: event.orderId };
  }

  if (order.status !== 'pending') {
    markEventProcessed(event.eventId);

    return { kind: 'already_settled', orderId: order.id, status: order.status };
  }

  // 金額が合わない通知は適用しない。人が調べるべき食い違いである
  if (event.amount !== order.totalAmount) {
    const mismatch = { orderId: order.id, expected: order.totalAmount, received: event.amount };

    logger.error('webhook.amount_mismatch', mismatch);

    return { kind: 'amount_mismatch', ...mismatch };
  }

  const succeeded = event.type === 'payment.succeeded';
  const key = buildIdempotencyKey(String(order.id));
  // 成功なら paid へ進め、失敗なら補償処理を走らせる。どちらも
  // 条件付き更新なので、2回目は false が返って何も起きない
  const applied = succeeded
    ? await markOrderPaid(order.id, order.totalAmount, key)
    : await cancelOrderAndReleaseStock(order.id);
  const status = succeeded ? 'paid' : 'cancelled';

  markEventProcessed(event.eventId);
  revalidateTag(PRODUCTS_TAG);

  return applied
    ? { kind: 'applied', orderId: order.id, status }
    : { kind: 'already_settled', orderId: order.id, status };
}

/**
 * pending のまま時間が過ぎた注文を取り消し、在庫を戻す。戻した件数を返す。
 * 本来は定期実行（cron）で回す処理だが、本書では管理画面のボタンから呼ぶ。
 */
export async function cancelStalePendingOrders(now: number = Date.now()): Promise<number> {
  const ids = await findStalePendingOrderIds(new Date(now - PENDING_ORDER_TTL_MS));
  let cancelled = 0;

  for (const id of ids) {
    const done = await cancelOrderAndReleaseStock(id);

    if (done) {
      cancelled += 1;
    }
  }

  if (cancelled > 0) {
    revalidateTag(PRODUCTS_TAG);
  }

  return cancelled;
}
