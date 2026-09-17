// 最終プロジェクトの核心ロジック（Next.js と Prisma から切り離した版）。
//
// src からは web を import できないため、web 側の実装と同じ仕様をここに写している。
// 写す対象は次の6つで、いずれも「引数だけで結果が決まる」形にしてある。
//   1. 支払総額の計算（本書共通の正典の手順）        … web/lib/pricing.ts
//   2. 注文ステータスの遷移                          … web/lib/order-status.ts
//   3. 決済ゲートウェイのスタブ（冪等キー）          … web/lib/payment/gateway.ts
//   4. Webhook の署名（HMAC-SHA256）の作成と検証     … web/lib/payment/webhook.ts
//   5. 在庫引当・注文確定・補償処理                  … web/lib/checkout.ts
//   6. 認可（他人の注文が見えないこと）              … web/lib/authz.ts
//
// 検証は verify.ts（一括の検算）と final.test.ts（Vitest）の2か所から行う。

import { createHmac, timingSafeEqual } from 'node:crypto';
import { z } from 'zod';

// ===========================================================================
// 1. 金額 — 支払総額の計算手順は全章共通の正典（順序と丸めを変えない）
// ===========================================================================

export const TAX_RATE = 0.1;
export const SHIPPING_FEE = 500;
export const FREE_SHIPPING_THRESHOLD = 3000;
export const MAX_CART_QUANTITY = 10;

/** 商品。7フィールドすべてを持つ正式な形（セッション11で決めた約束） */
export type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

/** 金額計算・表示に使う最小限のカート明細（セッション12で決めた形） */
export type CartLine = { product: Product; quantity: number };

export type PaymentSummary = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

export type DiscountRule = (subtotal: number) => number;

export const noDiscount: DiscountRule = () => 0;

export function calcLineTotal(price: number, quantity: number): number {
  return price * quantity;
}

export function calcSubtotal(lines: readonly CartLine[]): number {
  return lines.reduce((total, line) => total + calcLineTotal(line.product.price, line.quantity), 0);
}

/** 送料。判定の基準は税込商品合計（手順5）であって、税抜小計ではない */
export function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** 明細から支払総額の内訳を作る。丸めは消費税の計算時に一度だけ */
export function buildPaymentSummary(
  lines: readonly CartLine[],
  rule: DiscountRule = noDiscount
): PaymentSummary {
  const subtotal = calcSubtotal(lines);
  const discountAmount = Math.min(Math.floor(rule(subtotal)), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);

  return {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount: totalWithTax + shippingFee,
  };
}

/** 商品マスタ。fixtures/products.json・prisma/seed.ts と同じ値（在庫は 24 / 12 / 3 / 0 / 5） */
export const MASTER_PRODUCTS: readonly Product[] = [
  {
    id: 1,
    name: 'ラベンダーの石けん',
    price: 480,
    stock: 24,
    description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
    imageUrl: '/images/products/lavender-soap.png',
    categoryId: 1,
  },
  {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    stock: 12,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png',
    categoryId: 1,
  },
  {
    id: 3,
    name: 'マグカップ',
    price: 2350,
    stock: 3,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
    imageUrl: '/images/products/mug.png',
    categoryId: 2,
  },
  {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
    description: '洗うほどやわらかくなるリネン100%のふきんです。',
    imageUrl: '/images/products/linen-cloth.png',
    categoryId: 3,
  },
  {
    id: 5,
    name: 'コットンのトートバッグ',
    price: 2800,
    stock: 5,
    description: 'A4サイズが入る、しっかりした厚手のトートバッグです。',
    imageUrl: '/images/products/tote-bag.png',
    categoryId: 3,
  },
];

/** 商品マスタから明細を組み立てる。知らない id を渡したら例外（プログラムの誤りなので投げる） */
export function buildCartLines(
  entries: readonly { productId: number; quantity: number }[]
): CartLine[] {
  return entries.map((entry) => {
    const product = MASTER_PRODUCTS.find((candidate) => candidate.id === entry.productId);

    if (product === undefined) {
      throw new Error(`商品マスタに無い商品IDです: ${entry.productId}`);
    }

    return { product, quantity: entry.quantity };
  });
}

// ===========================================================================
// 2. 注文ステータスとその遷移
// ===========================================================================

export type OrderStatus = 'pending' | 'paid' | 'shipped' | 'cancelled';

export const ORDER_STATUSES = ['pending', 'paid', 'shipped', 'cancelled'] as const;

/** データベースの status カラム（文字列）をアプリのリテラル型に変換する */
export function parseOrderStatus(raw: string): OrderStatus {
  return ORDER_STATUSES.find((status) => status === raw) ?? 'pending';
}

/**
 * その状態から次に進める先。
 * default で never に代入しているので、状態を増やしたらここで型エラーになる（セッション12）。
 */
export function nextStatuses(from: OrderStatus): readonly OrderStatus[] {
  switch (from) {
    case 'pending':
      return ['paid', 'cancelled'];
    case 'paid':
      return ['shipped', 'cancelled'];
    case 'shipped':
      return [];
    case 'cancelled':
      return [];
    default: {
      const unreachable: never = from;

      throw new Error(`未知の注文ステータスです: ${String(unreachable)}`);
    }
  }
}

export function canTransitionTo(from: OrderStatus, to: OrderStatus): boolean {
  return nextStatuses(from).includes(to);
}

export function canCancelOrder(status: OrderStatus): boolean {
  return canTransitionTo(status, 'cancelled');
}

/** もう動かない状態か（発送済み・取消済みは終着点） */
export function isSettled(status: OrderStatus): boolean {
  return nextStatuses(status).length === 0;
}

export function describeOrderStatus(status: OrderStatus): string {
  switch (status) {
    case 'pending':
      return 'お支払いの確認中';
    case 'paid':
      return 'お支払い済み';
    case 'shipped':
      return '発送済み';
    case 'cancelled':
      return 'キャンセル';
    default: {
      const unreachable: never = status;

      throw new Error(`未知の注文ステータスです: ${String(unreachable)}`);
    }
  }
}

// ===========================================================================
// 3. 決済ゲートウェイのスタブ（API契約。章をまたいで形を変えない）
// ===========================================================================

export type PaymentResult =
  | { kind: 'succeeded'; paymentId: string }
  | { kind: 'failed'; reason: 'card_declined' | 'insufficient_funds' | 'network_error' }
  | { kind: 'pending'; paymentId: string };

/** 失敗の理由だけを取り出した型（セッション14のユーティリティ型） */
export type PaymentFailureReason = Extract<PaymentResult, { kind: 'failed' }>['reason'];

export type ChargeInput = {
  /** 二重決済を防ぐ冪等キー。同じキーの再送は同じ結果を返す */
  idempotencyKey: string;
  /** 請求金額（円・整数） */
  amount: number;
  orderId: string;
};

export interface PaymentGateway {
  charge(input: ChargeInput): Promise<PaymentResult>;
}

/** 冪等キーは「1回の支払い」に対して1つ。注文IDから作れば再送でも同じキーになる */
export function buildIdempotencyKey(orderId: string): string {
  return `charge-${orderId}`;
}

/** 金額の下2桁から結果を決める。01 は拒否、02 はタイムアウト（応答なし）、それ以外は成功 */
export function decidePaymentResult(input: ChargeInput): PaymentResult {
  const lastTwoDigits = Math.abs(Math.trunc(input.amount)) % 100;
  const paymentId = `pay_${input.idempotencyKey}`;

  switch (lastTwoDigits) {
    case 1:
      return { kind: 'failed', reason: 'card_declined' };
    case 2:
      return { kind: 'pending', paymentId };
    default:
      return { kind: 'succeeded', paymentId };
  }
}

/** 冪等キーごとに結果を覚えておくスタブ。2回目の同じキーでは課金しない */
export class StubPaymentGateway implements PaymentGateway {
  readonly #results = new Map<string, PaymentResult>();
  #chargeCount = 0;

  /** 実際に課金を試みた回数。「2回叩いても1回しか課金しない」ことの確認に使う */
  get chargeCount(): number {
    return this.#chargeCount;
  }

  async charge(input: ChargeInput): Promise<PaymentResult> {
    const remembered = this.#results.get(input.idempotencyKey);

    if (remembered !== undefined) {
      return remembered;
    }

    this.#chargeCount += 1;

    const result = decidePaymentResult(input);

    this.#results.set(input.idempotencyKey, result);

    return result;
  }
}

// ===========================================================================
// 4. Webhook の署名（HMAC-SHA256）とペイロードの検証
// ===========================================================================

/** 署名を載せるヘッダの名前。Headers.get は大文字小文字を区別しない */
export const SIGNATURE_HEADER = 'x-signature';

/** 使ったアルゴリズムを値に埋める。将来 sha512 に変えても両方を受けられる */
export const SIGNATURE_PREFIX = 'sha256=';

/**
 * 本文に署名を付ける。送り手（決済サービス）と受け手（このアプリ）が
 * 同じ秘密を持っていて、同じ計算をするからこそ一致する。
 */
export function signWebhookBody(body: string, secret: string): string {
  const digest = createHmac('sha256', secret).update(body, 'utf8').digest('hex');

  return `${SIGNATURE_PREFIX}${digest}`;
}

/**
 * 署名を検証する。
 * - ヘッダが無い・接頭辞が違う場合は即座に false（例外にしない）
 * - 比較は timingSafeEqual。長さが違うと例外を投げるので、先に長さを確かめる
 */
export function verifyWebhookSignature(
  body: string,
  header: string | null | undefined,
  secret: string
): boolean {
  if (header === null || header === undefined || !header.startsWith(SIGNATURE_PREFIX)) {
    return false;
  }

  const expected = Buffer.from(signWebhookBody(body, secret), 'utf8');
  const received = Buffer.from(header, 'utf8');

  // 長さが違えばそもそも別物。ここで返さないと timingSafeEqual が例外を投げる
  if (expected.length !== received.length) {
    return false;
  }

  // 1文字目から違っていても最後まで比べる（比較時間から正解を推測されないため）
  return timingSafeEqual(expected, received);
}

/** Webhook のペイロード。API契約で決めた5つのフィールド */
export const webhookEventSchema = z.object({
  eventId: z.string({ error: 'eventId が必要です' }).min(1, { error: 'eventId が必要です' }),
  type: z.enum(['payment.succeeded', 'payment.failed']),
  paymentId: z.string().min(1),
  // JSON では数値でも文字列でも届きうるので、境界で数値に寄せる
  orderId: z.coerce.number().int().positive(),
  amount: z.coerce.number().int().min(0),
});

export type PaymentWebhookEvent = z.infer<typeof webhookEventSchema>;

/** 生の本文をイベントに変換する。壊れていれば null（例外を外に出さない） */
export function parseWebhookBody(raw: string): PaymentWebhookEvent | null {
  let json: unknown;

  try {
    json = JSON.parse(raw);
  } catch {
    return null;
  }

  const parsed = webhookEventSchema.safeParse(json);

  return parsed.success ? parsed.data : null;
}

/** Webhook を適用した結果。判別タグは本書共通の kind */
export type WebhookOutcome =
  | { kind: 'applied'; orderId: number; status: 'paid' | 'cancelled' }
  | { kind: 'duplicate'; eventId: string }
  | { kind: 'already_settled'; orderId: number; status: OrderStatus }
  | { kind: 'unknown_order'; orderId: number }
  | { kind: 'amount_mismatch'; orderId: number; expected: number; received: number };

/**
 * 結果を HTTP のステータスコードに翻訳する。
 * 2xx は送り手にとって「もう再送しなくてよい」という返事なので、
 * 重複・処理済みには 200 を返す。人が調べる必要がある食い違いだけ 4xx にする。
 */
export function statusForOutcome(outcome: WebhookOutcome): 200 | 404 | 409 {
  switch (outcome.kind) {
    case 'applied':
    case 'duplicate':
    case 'already_settled':
      return 200;
    case 'unknown_order':
      return 404;
    case 'amount_mismatch':
      return 409;
    default: {
      const unreachable: never = outcome;

      throw new Error(`未知の結果です: ${JSON.stringify(unreachable)}`);
    }
  }
}

// ===========================================================================
// 5. 在庫引当・注文確定・補償処理
// ===========================================================================

export type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

export type CheckoutFailure =
  | { kind: 'empty_cart' }
  | { kind: 'invalid_quantity'; productName: string; quantity: number }
  | { kind: 'stock_conflict'; productName: string }
  | { kind: 'payment_declined'; orderId: number; reason: PaymentFailureReason };

/** 注文は作れた場合の結果。支払いが確定したか、確認中かの2つ */
export type CheckoutSuccess =
  | { kind: 'paid'; orderId: number; payableAmount: number }
  | { kind: 'pending'; orderId: number };

export type CheckoutResult = Result<CheckoutSuccess, CheckoutFailure>;

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

export type OrderItemRecord = { productId: number; quantity: number; unitPrice: number };

export type OrderRecord = {
  id: number;
  userId: number;
  status: OrderStatus;
  totalAmount: number;
  /** エポックミリ秒。時刻は外から渡す（テストで実時間を待たないため） */
  createdAt: number;
  items: readonly OrderItemRecord[];
};

export type PaymentRecord = { status: string; amount: number; idempotencyKey: string };

/** pending のまま放置された注文を打ち切るまでの時間（ミリ秒）。15分 */
export const PENDING_ORDER_TTL_MS = 15 * 60 * 1000;

/** その注文はもう待つのをやめてよいか */
export function isStalePending(
  order: { status: OrderStatus; createdAt: number },
  now: number,
  ttlMs: number = PENDING_ORDER_TTL_MS
): boolean {
  return order.status === 'pending' && now - order.createdAt >= ttlMs;
}

export type SessionUser = {
  id: number;
  email: string;
  name: string;
  role: 'user' | 'admin';
};

/**
 * その注文を見てよいか。本書の方針は「自分の注文だけ」。
 * 管理者もこの関数では他人の注文を見られない（管理者は管理画面という別の入口から見る）。
 */
export function canViewOrder(
  user: SessionUser | undefined,
  order: { userId: number }
): boolean {
  return user !== undefined && order.userId === user.id;
}

/**
 * メモリ上の小さな店。データベースの代わりに Map で在庫・注文・決済・受信済みイベントを持つ。
 *
 * web/lib/checkout.ts との違いは「原子性の作り方」だけである。
 *   - こちら : すべて同期処理なので、確認してから減らすあいだに割り込まれない
 *   - web 側 : 割り込まれるので $transaction ＋条件付き更新（stock: { gte: quantity }）で守る
 * 判定の結果（何を成功とし、何を失敗とし、どう戻すか）は同じにしてある。
 */
export class ShopState {
  readonly #products = new Map<number, Product>();
  readonly #stock = new Map<number, number>();
  readonly #orders = new Map<number, OrderRecord>();
  readonly #payments = new Map<number, PaymentRecord>();
  readonly #processedEvents = new Set<string>();
  #nextOrderId = 1;

  constructor(products: readonly Product[] = MASTER_PRODUCTS) {
    for (const product of products) {
      this.#products.set(product.id, product);
      this.#stock.set(product.id, product.stock);
    }
  }

  stockOf(productId: number): number {
    return this.#stock.get(productId) ?? 0;
  }

  /** 商品ID順の在庫の並び。マスタの値は [24, 12, 3, 0, 5] */
  stockSnapshot(): number[] {
    return [...this.#products.keys()].sort((left, right) => left - right).map((id) => this.stockOf(id));
  }

  orderCount(): number {
    return this.#orders.size;
  }

  statusOf(orderId: number): OrderStatus | undefined {
    return this.#orders.get(orderId)?.status;
  }

  paymentOf(orderId: number): PaymentRecord | undefined {
    return this.#payments.get(orderId);
  }

  /** その利用者の注文だけを返す。where に userId を入れるのと同じ考え方 */
  ordersFor(userId: number): OrderRecord[] {
    return [...this.#orders.values()].filter((order) => order.userId === userId);
  }

  /** 注文1件。「自分のものか」を取得の条件に含める（取ってから if で確かめない） */
  findOrderForUser(orderId: number, userId: number): OrderRecord | undefined {
    const order = this.#orders.get(orderId);

    return order !== undefined && order.userId === userId ? order : undefined;
  }

  #judgeQuantities(lines: readonly CartLine[]): CheckoutFailure | null {
    for (const line of lines) {
      if (
        !Number.isInteger(line.quantity) ||
        line.quantity < 1 ||
        line.quantity > MAX_CART_QUANTITY
      ) {
        return {
          kind: 'invalid_quantity',
          productName: line.product.name,
          quantity: line.quantity,
        };
      }
    }

    return null;
  }

  /** 全明細を引き当てる。1つでも足りなければ1つも減らさない（部分的な引当を残さない） */
  #reserve(lines: readonly CartLine[]): CheckoutFailure | null {
    for (const line of lines) {
      if (this.stockOf(line.product.id) < line.quantity) {
        return { kind: 'stock_conflict', productName: line.product.name };
      }
    }

    for (const line of lines) {
      this.#stock.set(line.product.id, this.stockOf(line.product.id) - line.quantity);
    }

    return null;
  }

  /** 引き当てた在庫を戻す（補償処理） */
  #release(items: readonly OrderItemRecord[]): void {
    for (const item of items) {
      this.#stock.set(item.productId, this.stockOf(item.productId) + item.quantity);
    }
  }

  /**
   * 支払い済みにする。pending 以外なら何もせず false を返す。
   * web 側の「条件付き更新（where に status: 'pending' を入れる）」に相当する。
   */
  markPaid(orderId: number, idempotencyKey: string): boolean {
    const order = this.#orders.get(orderId);

    if (order === undefined || !canTransitionTo(order.status, 'paid')) {
      return false;
    }

    this.#orders.set(orderId, { ...order, status: 'paid' });
    this.#payments.set(orderId, {
      status: 'succeeded',
      amount: order.totalAmount,
      idempotencyKey,
    });

    return true;
  }

  /**
   * 注文を取り消し、引き当てた在庫を戻す。
   * pending 以外なら何もしないので、2回呼んでも在庫は二重に戻らない。
   */
  cancelOrder(orderId: number): boolean {
    const order = this.#orders.get(orderId);

    if (order === undefined || order.status !== 'pending') {
      return false;
    }

    this.#orders.set(orderId, { ...order, status: 'cancelled' });
    this.#release(order.items);

    const payment = this.#payments.get(orderId);

    if (payment !== undefined) {
      this.#payments.set(orderId, { ...payment, status: 'failed' });
    }

    return true;
  }

  /** 発送する。paid からしか進めない */
  shipOrder(orderId: number): boolean {
    const order = this.#orders.get(orderId);

    if (order === undefined || !canTransitionTo(order.status, 'shipped')) {
      return false;
    }

    this.#orders.set(orderId, { ...order, status: 'shipped' });

    return true;
  }

  /**
   * 注文を確定する。手順は web 側とまったく同じ。
   *   1. カートが空なら失敗
   *   2. 数量を検証
   *   3. 在庫を引き当て、pending の注文と明細（そのときの単価）を作る
   *   4. 決済を呼ぶ（冪等キーは charge-<orderId>）
   *   5. 成功 → paid ／ 拒否 → 補償して cancelled ／ 応答なし → pending のまま Webhook を待つ
   */
  async placeOrder(
    userId: number,
    lines: readonly CartLine[],
    gateway: PaymentGateway,
    now: number = 0
  ): Promise<CheckoutResult> {
    if (lines.length === 0) {
      return { kind: 'error', error: { kind: 'empty_cart' } };
    }

    const invalid = this.#judgeQuantities(lines);

    if (invalid !== null) {
      return { kind: 'error', error: invalid };
    }

    const summary = buildPaymentSummary(lines);
    const conflict = this.#reserve(lines);

    if (conflict !== null) {
      return { kind: 'error', error: conflict };
    }

    const orderId = this.#nextOrderId;

    this.#nextOrderId += 1;
    this.#orders.set(orderId, {
      id: orderId,
      userId,
      status: 'pending',
      totalAmount: summary.payableAmount,
      createdAt: now,
      // 単価は「注文した時点の価格」を写して持つ。あとで値段が変わっても金額は動かない
      items: lines.map((line) => ({
        productId: line.product.id,
        quantity: line.quantity,
        unitPrice: line.product.price,
      })),
    });

    const idempotencyKey = buildIdempotencyKey(String(orderId));
    // 決済はトランザクションの外で呼ぶ。外部の応答を待つあいだ行のロックを持たないため
    const result = await gateway.charge({
      idempotencyKey,
      amount: summary.payableAmount,
      orderId: String(orderId),
    });

    switch (result.kind) {
      case 'succeeded': {
        this.markPaid(orderId, idempotencyKey);

        return {
          kind: 'ok',
          value: { kind: 'paid', orderId, payableAmount: summary.payableAmount },
        };
      }
      case 'pending': {
        // 在庫は保持したまま Webhook の到着を待つ。待ちきれない分は掃除の処理が取り消す
        this.#payments.set(orderId, {
          status: 'pending',
          amount: summary.payableAmount,
          idempotencyKey,
        });

        return { kind: 'ok', value: { kind: 'pending', orderId } };
      }
      case 'failed': {
        this.cancelOrder(orderId);

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

  /** Webhook を1件適用する。同じ eventId を2回受けても状態は変わらない */
  applyWebhookEvent(event: PaymentWebhookEvent): WebhookOutcome {
    if (this.#processedEvents.has(event.eventId)) {
      return { kind: 'duplicate', eventId: event.eventId };
    }

    const order = this.#orders.get(event.orderId);

    if (order === undefined) {
      return { kind: 'unknown_order', orderId: event.orderId };
    }

    if (order.status !== 'pending') {
      this.#processedEvents.add(event.eventId);

      return { kind: 'already_settled', orderId: order.id, status: order.status };
    }

    // 金額が合わないイベントは適用しない。人が調べる必要がある食い違いである
    if (event.amount !== order.totalAmount) {
      return {
        kind: 'amount_mismatch',
        orderId: order.id,
        expected: order.totalAmount,
        received: event.amount,
      };
    }

    this.#processedEvents.add(event.eventId);

    if (event.type === 'payment.succeeded') {
      this.markPaid(order.id, buildIdempotencyKey(String(order.id)));

      return { kind: 'applied', orderId: order.id, status: 'paid' };
    }

    this.cancelOrder(order.id);

    return { kind: 'applied', orderId: order.id, status: 'cancelled' };
  }

  /** pending のまま時間が過ぎた注文を取り消し、在庫を戻す。戻した件数を返す */
  cancelStalePending(now: number, ttlMs: number = PENDING_ORDER_TTL_MS): number {
    let cancelled = 0;

    for (const order of [...this.#orders.values()]) {
      if (isStalePending(order, now, ttlMs) && this.cancelOrder(order.id)) {
        cancelled += 1;
      }
    }

    return cancelled;
  }
}
