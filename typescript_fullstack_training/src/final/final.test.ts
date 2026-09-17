// 最終プロジェクトのユニットテスト（Vitest）。
//
// verify.ts が「全部まとめて検算する台本」なのに対し、こちらは
// 「壊れたときにどこが壊れたかを名前で示す」ためのテストである。
// 落としてはいけない4つの性質だけを、それぞれ独立した it に分けて書く。
//
//   1. 冪等性     … 同じ冪等キーで2回呼んでも1回しか課金されない
//   2. 署名検証   … 正しい署名だけを通す
//   3. 補償処理   … 決済が失敗したら在庫がマスタの値に戻る
//   4. 認可       … 他人の注文が見えない
//
// 実行: docker compose exec ts npx vitest run src/final
// （このサンドボックスでは globals を有効にしていないので、describe / it / expect は明示的に import する）

import { describe, expect, it } from 'vitest';
import {
  ShopState,
  StubPaymentGateway,
  buildCartLines,
  buildIdempotencyKey,
  buildPaymentSummary,
  canViewOrder,
  signWebhookBody,
  verifyWebhookSignature,
  type SessionUser,
} from './checkout-core';

const MASTER_STOCK = [24, 12, 3, 0, 5];

/** 石けん×2 ＋ マグカップ×1 → 3641円（下2桁 41 なので成功する） */
const CART_SUCCESS = buildCartLines([
  { productId: 1, quantity: 2 },
  { productId: 3, quantity: 1 },
]);

/** 上に ハンドクリーム×2 を足す → 7601円（下2桁 01 なのでカードが拒否される） */
const CART_DECLINED = buildCartLines([
  { productId: 1, quantity: 2 },
  { productId: 2, quantity: 2 },
  { productId: 3, quantity: 1 },
]);

describe('支払総額', () => {
  it('送料は税抜小計ではなく税込商品合計で判定する', () => {
    // 税抜2400円は3000円未満、税込2640円も3000円未満なので送料がかかる
    expect(buildPaymentSummary(buildCartLines([{ productId: 1, quantity: 5 }]))).toEqual({
      subtotal: 2400,
      discountAmount: 0,
      discountedTotal: 2400,
      tax: 240,
      totalWithTax: 2640,
      shippingFee: 500,
      payableAmount: 3140,
    });
  });

  it('税込商品合計が3000円以上なら送料が無料になる', () => {
    const summary = buildPaymentSummary(buildCartLines([{ productId: 1, quantity: 6 }]));

    expect(summary.totalWithTax).toBe(3168);
    expect(summary.shippingFee).toBe(0);
    expect(summary.payableAmount).toBe(3168);
  });
});

describe('決済の冪等性', () => {
  it('同じ冪等キーで2回呼んでも課金は1回で、同じ結果が返る', async () => {
    const gateway = new StubPaymentGateway();
    const input = { idempotencyKey: buildIdempotencyKey('1'), amount: 3641, orderId: '1' };

    const first = await gateway.charge(input);
    // 送信ボタンの二度押し。金額を書き換えられていても1回目の結果が返る
    const second = await gateway.charge({ ...input, amount: 999_999 });

    expect(gateway.chargeCount).toBe(1);
    expect(second).toEqual(first);
    expect(first).toEqual({ kind: 'succeeded', paymentId: 'pay_charge-1' });
  });

  it('別の注文は別のキーになるので、それぞれ課金される', async () => {
    const gateway = new StubPaymentGateway();

    await gateway.charge({ idempotencyKey: buildIdempotencyKey('1'), amount: 3641, orderId: '1' });
    await gateway.charge({ idempotencyKey: buildIdempotencyKey('2'), amount: 3641, orderId: '2' });

    expect(gateway.chargeCount).toBe(2);
  });
});

describe('Webhook の署名検証', () => {
  const secret = 'final-project-webhook-secret';
  const body = JSON.stringify({
    eventId: 'evt_1',
    type: 'payment.succeeded',
    paymentId: 'pay_charge-1',
    orderId: 1,
    amount: 3641,
  });

  it('正しい署名は通る', () => {
    expect(verifyWebhookSignature(body, signWebhookBody(body, secret), secret)).toBe(true);
  });

  it('1文字違う署名は弾く', () => {
    const signature = signWebhookBody(body, secret);
    const last = signature.slice(-1);
    const tampered = `${signature.slice(0, -1)}${last === '0' ? '1' : '0'}`;

    expect(verifyWebhookSignature(body, tampered, secret)).toBe(false);
  });

  it('本文を書き換えられたら弾く', () => {
    const signature = signWebhookBody(body, secret);

    expect(verifyWebhookSignature(body.replace('3641', '1'), signature, secret)).toBe(false);
  });

  it('ヘッダが無い・接頭辞が無い・長さが違う場合も例外にせず弾く', () => {
    const signature = signWebhookBody(body, secret);

    expect(verifyWebhookSignature(body, null, secret)).toBe(false);
    expect(verifyWebhookSignature(body, signature.slice('sha256='.length), secret)).toBe(false);
    expect(verifyWebhookSignature(body, 'sha256=00ff', secret)).toBe(false);
  });
});

describe('補償処理', () => {
  it('決済が失敗したら在庫がマスタの値に戻り、注文は取り消される', async () => {
    const state = new ShopState();
    const gateway = new StubPaymentGateway();

    const result = await state.placeOrder(1, CART_DECLINED, gateway);

    expect(result).toEqual({
      kind: 'error',
      error: { kind: 'payment_declined', orderId: 1, reason: 'card_declined' },
    });
    expect(state.stockSnapshot()).toEqual(MASTER_STOCK);
    expect(state.statusOf(1)).toBe('cancelled');
  });

  it('補償を2回行っても在庫は二重に戻らない', async () => {
    const state = new ShopState();
    const gateway = new StubPaymentGateway();

    await state.placeOrder(1, CART_DECLINED, gateway);

    // すでに cancelled なので、条件付き更新にあたる判定で弾かれる
    expect(state.cancelOrder(1)).toBe(false);
    expect(state.stockSnapshot()).toEqual(MASTER_STOCK);
  });

  it('在庫が足りない明細が1つでもあれば、他の商品の在庫も減らさない', async () => {
    const state = new ShopState();
    const gateway = new StubPaymentGateway();

    const result = await state.placeOrder(
      1,
      buildCartLines([
        { productId: 1, quantity: 1 },
        // 在庫0の商品
        { productId: 4, quantity: 1 },
      ]),
      gateway
    );

    expect(result).toEqual({
      kind: 'error',
      error: { kind: 'stock_conflict', productName: 'リネンのふきん' },
    });
    expect(state.stockSnapshot()).toEqual(MASTER_STOCK);
    expect(state.orderCount()).toBe(0);
    // 在庫を押さえられていないのだから、決済を呼んではいけない
    expect(gateway.chargeCount).toBe(0);
  });
});

describe('注文の認可（IDOR 対策）', () => {
  const demo: SessionUser = { id: 1, email: 'demo@example.com', name: 'デモ', role: 'user' };
  const admin: SessionUser = { id: 2, email: 'admin@example.com', name: '店長', role: 'admin' };
  const other: SessionUser = { id: 3, email: 'other@example.com', name: '別の客', role: 'user' };

  it('自分の注文だけが見える', () => {
    const order = { userId: demo.id };

    expect(canViewOrder(demo, order)).toBe(true);
    expect(canViewOrder(other, order)).toBe(false);
    // 管理者もこの入口では他人の注文を見られない
    expect(canViewOrder(admin, order)).toBe(false);
    expect(canViewOrder(undefined, order)).toBe(false);
  });

  it('一覧にも他人の注文が混ざらない', async () => {
    const state = new ShopState();
    const gateway = new StubPaymentGateway();

    await state.placeOrder(demo.id, CART_SUCCESS, gateway);
    await state.placeOrder(other.id, CART_SUCCESS, gateway);

    expect(state.ordersFor(demo.id).map((order) => order.id)).toEqual([1]);
    expect(state.ordersFor(other.id).map((order) => order.id)).toEqual([2]);
    // ID を直接指定しても取れない
    expect(state.findOrderForUser(2, demo.id)).toBeUndefined();
  });
});
