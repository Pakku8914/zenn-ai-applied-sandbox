// 最終プロジェクト「ECサイト ミニ雑貨ショップ」の検証スクリプト。
//
// 画面（.tsx）とデータベースを使う部分は検証できないので、この章の核心である
// 「壊れないための判断」だけを取り出して確かめる。
//
//   1. 支払総額 … 商品マスタから計算した確定値と一致するか（送料は税込商品合計で判定）
//   2. 決済スタブの契約 … 金額の下2桁で結果が決まる
//   3. 冪等キー … 同じキーで2回呼んでも1回しか課金されず、同じ結果が返る
//   4. Webhook の署名 … 正しい署名を通し、1文字違う署名を弾く
//   5. 在庫引当と補償 … 決済が失敗したら在庫がマスタの値に戻る
//   6. 注文ステータスの遷移 … 進めてよい組み合わせだけを通す
//   7. Webhook の重複受信 … 同じ eventId を2回受けても状態が変わらない
//   8. IDOR … 他人の注文が1件も見えない（全組み合わせ）
//
// 実行: docker compose exec ts npx tsx src/final/verify.ts

import {
  MASTER_PRODUCTS,
  ORDER_STATUSES,
  PENDING_ORDER_TTL_MS,
  ShopState,
  StubPaymentGateway,
  buildCartLines,
  buildIdempotencyKey,
  buildPaymentSummary,
  canCancelOrder,
  canTransitionTo,
  canViewOrder,
  decidePaymentResult,
  describeCheckoutFailure,
  describeOrderStatus,
  isSettled,
  isStalePending,
  parseOrderStatus,
  parseWebhookBody,
  signWebhookBody,
  statusForOutcome,
  verifyWebhookSignature,
  type CheckoutResult,
  type OrderStatus,
  type PaymentWebhookEvent,
  type SessionUser,
} from './checkout-core';

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label}\n--- 期待値 ---\n${expected}\n--- 実際 ---\n${actual}`);
    failedCount += 1;
  }
}

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${String(expected)} / 実際 ${String(actual)}`);
    failedCount += 1;
  }
}

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ---------------------------------------------------------------------------
// 章を通して使うカート（商品マスタから作る）
// ---------------------------------------------------------------------------

/** 成功する注文：石けん×2 ＋ マグカップ×1 → 支払総額 3641円（下2桁 41） */
const CART_SUCCESS = buildCartLines([
  { productId: 1, quantity: 2 },
  { productId: 3, quantity: 1 },
]);

/** カードが拒否される注文：上に ハンドクリーム×2 を足す → 7601円（下2桁 01） */
const CART_DECLINED = buildCartLines([
  { productId: 1, quantity: 2 },
  { productId: 2, quantity: 2 },
  { productId: 3, quantity: 1 },
]);

/** 応答が返ってこない注文：拒否される注文の数量を2倍にする → 15202円（下2桁 02） */
const CART_TIMEOUT = buildCartLines([
  { productId: 1, quantity: 4 },
  { productId: 2, quantity: 4 },
  { productId: 3, quantity: 2 },
]);

/** 送料がかかる注文：石けん×2 のみ → 税込1056円 ＋ 送料500円 = 1556円 */
const CART_WITH_SHIPPING = buildCartLines([{ productId: 1, quantity: 2 }]);

/** 商品マスタの在庫。補償処理のあとにここへ戻ることを確かめる */
const MASTER_STOCK = [24, 12, 3, 0, 5];

// ===========================================================================
// 1. 支払総額（正典の手順。送料の判定は税込商品合計）
// ===========================================================================

checkJson('1: マスタの在庫は 24 / 12 / 3 / 0 / 5', MASTER_PRODUCTS.map((product) => product.stock), MASTER_STOCK);

checkJson('1: 成功する注文の内訳', buildPaymentSummary(CART_SUCCESS), {
  subtotal: 3310,
  discountAmount: 0,
  discountedTotal: 3310,
  tax: 331,
  totalWithTax: 3641,
  shippingFee: 0,
  payableAmount: 3641,
});
checkJson('1: 拒否される注文の内訳', buildPaymentSummary(CART_DECLINED), {
  subtotal: 6910,
  discountAmount: 0,
  discountedTotal: 6910,
  tax: 691,
  totalWithTax: 7601,
  shippingFee: 0,
  payableAmount: 7601,
});
checkJson('1: 応答が返らない注文の内訳', buildPaymentSummary(CART_TIMEOUT), {
  subtotal: 13820,
  discountAmount: 0,
  discountedTotal: 13820,
  tax: 1382,
  totalWithTax: 15202,
  shippingFee: 0,
  payableAmount: 15202,
});
checkJson('1: 送料がかかる注文の内訳', buildPaymentSummary(CART_WITH_SHIPPING), {
  subtotal: 960,
  discountAmount: 0,
  discountedTotal: 960,
  tax: 96,
  totalWithTax: 1056,
  shippingFee: 500,
  payableAmount: 1556,
});

// 送料無料の境界。判定に使うのは税込商品合計（2640円）であって税抜小計（2400円）ではない
const fiveSoaps = buildPaymentSummary(buildCartLines([{ productId: 1, quantity: 5 }]));
const sixSoaps = buildPaymentSummary(buildCartLines([{ productId: 1, quantity: 6 }]));

checkNumber('1: 石けん5個の税込商品合計', fiveSoaps.totalWithTax, 2640);
checkNumber('1: 石けん5個は送料がかかる', fiveSoaps.shippingFee, 500);
checkNumber('1: 石けん5個の支払総額', fiveSoaps.payableAmount, 3140);
checkNumber('1: 石けん6個の税込商品合計', sixSoaps.totalWithTax, 3168);
checkNumber('1: 石けん6個は送料無料', sixSoaps.shippingFee, 0);
checkNumber('1: 石けん6個の支払総額', sixSoaps.payableAmount, 3168);

// 空のカートでも式は動くが、支払総額 500円（送料だけ）になる。
// だから注文確定は金額の計算より前に「空かどうか」を確かめる必要がある
checkNumber('1: 空のカートは送料だけが残る', buildPaymentSummary([]).payableAmount, 500);

// ===========================================================================
// 2. 決済スタブの契約（金額の下2桁で結果が決まる）
// ===========================================================================

checkString('2: 冪等キーは注文IDから作る', buildIdempotencyKey('12'), 'charge-12');

checkJson(
  '2: 下2桁が41なら成功',
  decidePaymentResult({ idempotencyKey: 'charge-1', amount: 3641, orderId: '1' }),
  { kind: 'succeeded', paymentId: 'pay_charge-1' }
);
checkJson(
  '2: 下2桁が00でも成功',
  decidePaymentResult({ idempotencyKey: 'charge-2', amount: 3600, orderId: '2' }),
  { kind: 'succeeded', paymentId: 'pay_charge-2' }
);
checkJson(
  '2: 下2桁が01ならカード拒否',
  decidePaymentResult({ idempotencyKey: 'charge-3', amount: 7601, orderId: '3' }),
  { kind: 'failed', reason: 'card_declined' }
);
checkJson(
  '2: 下2桁が02なら応答なし（保留）',
  decidePaymentResult({ idempotencyKey: 'charge-4', amount: 15202, orderId: '4' }),
  { kind: 'pending', paymentId: 'pay_charge-4' }
);
checkJson(
  '2: 1円でも下2桁は01として扱う',
  decidePaymentResult({ idempotencyKey: 'charge-5', amount: 1, orderId: '5' }),
  { kind: 'failed', reason: 'card_declined' }
);

// ===========================================================================
// 3. 冪等キー（同じキーの2回目は課金しない）
// ===========================================================================

async function verifyIdempotency(): Promise<void> {
  const gateway = new StubPaymentGateway();
  const first = await gateway.charge({ idempotencyKey: 'charge-7', amount: 3641, orderId: '7' });
  // 通信の失敗で読者がもう一度送信した状況。金額を書き換えられても結果は変わらない
  const second = await gateway.charge({ idempotencyKey: 'charge-7', amount: 999999, orderId: '7' });

  checkNumber('3: 同じ冪等キーなら課金は1回だけ', gateway.chargeCount, 1);
  checkJson('3: 2回目も同じ結果が返る', second, first);
  checkJson('3: 返るのは1回目の結果', first, { kind: 'succeeded', paymentId: 'pay_charge-7' });

  const third = await gateway.charge({ idempotencyKey: 'charge-8', amount: 3641, orderId: '8' });

  checkNumber('3: 別の注文なら別の課金になる', gateway.chargeCount, 2);
  checkJson('3: 別の注文の結果', third, { kind: 'succeeded', paymentId: 'pay_charge-8' });
}

// ===========================================================================
// 4. Webhook の署名（HMAC-SHA256）
// ===========================================================================

const WEBHOOK_SECRET = 'final-project-webhook-secret';

const SUCCEEDED_EVENT: PaymentWebhookEvent = {
  eventId: 'evt_20260901_0001',
  type: 'payment.succeeded',
  paymentId: 'pay_charge-1',
  orderId: 1,
  amount: 15202,
};

const eventBody = JSON.stringify(SUCCEEDED_EVENT);
const eventSignature = signWebhookBody(eventBody, WEBHOOK_SECRET);

/** 署名の最後の1文字だけを変える（人の目には気づけない改ざん） */
function flipLastHexChar(signature: string): string {
  const last = signature.slice(-1);

  return `${signature.slice(0, -1)}${last === '0' ? '1' : '0'}`;
}

checkBoolean('4: 署名は sha256= で始まる', eventSignature.startsWith('sha256='), true);
checkNumber('4: 署名の長さは 7 + 64 文字', eventSignature.length, 71);
checkBoolean(
  '4: 正しい署名は通る',
  verifyWebhookSignature(eventBody, eventSignature, WEBHOOK_SECRET),
  true
);
checkBoolean(
  '4: 1文字違う署名は弾く',
  verifyWebhookSignature(eventBody, flipLastHexChar(eventSignature), WEBHOOK_SECRET),
  false
);
checkBoolean(
  '4: 接頭辞が無い署名は弾く',
  verifyWebhookSignature(eventBody, eventSignature.slice('sha256='.length), WEBHOOK_SECRET),
  false
);
checkBoolean('4: ヘッダが無ければ弾く', verifyWebhookSignature(eventBody, null, WEBHOOK_SECRET), false);
checkBoolean(
  '4: ヘッダが空文字でも弾く',
  verifyWebhookSignature(eventBody, '', WEBHOOK_SECRET),
  false
);
checkBoolean(
  '4: 長さが違う署名でも例外にならず弾く',
  verifyWebhookSignature(eventBody, 'sha256=00ff', WEBHOOK_SECRET),
  false
);
checkBoolean(
  '4: 本文が1文字でも違えば弾く',
  verifyWebhookSignature(`${eventBody} `, eventSignature, WEBHOOK_SECRET),
  false
);
checkBoolean(
  '4: 秘密が違えば弾く',
  verifyWebhookSignature(eventBody, eventSignature, 'wrong-secret'),
  false
);
// 同じ本文と同じ秘密からは必ず同じ署名が出る（決定的である）
checkString('4: 署名は決定的', signWebhookBody(eventBody, WEBHOOK_SECRET), eventSignature);

// --- ペイロードの検証（入口で形を確かめる） ---------------------------------
checkJson('4: 正しいペイロードを解釈できる', parseWebhookBody(eventBody), SUCCEEDED_EVENT);
checkJson(
  '4: orderId が文字列でも数値に寄せる',
  parseWebhookBody('{"eventId":"e1","type":"payment.failed","paymentId":"p1","orderId":"3","amount":"100"}'),
  { eventId: 'e1', type: 'payment.failed', paymentId: 'p1', orderId: 3, amount: 100 }
);
checkBoolean('4: 壊れた JSON は null', parseWebhookBody('{"eventId":') === null, true);
checkBoolean(
  '4: 知らない type は null',
  parseWebhookBody('{"eventId":"e1","type":"payment.refunded","paymentId":"p1","orderId":1,"amount":1}') ===
    null,
  true
);
checkBoolean(
  '4: eventId が空なら null',
  parseWebhookBody('{"eventId":"","type":"payment.succeeded","paymentId":"p1","orderId":1,"amount":1}') ===
    null,
  true
);
checkBoolean(
  '4: orderId が0なら null',
  parseWebhookBody('{"eventId":"e1","type":"payment.succeeded","paymentId":"p1","orderId":0,"amount":1}') ===
    null,
  true
);

// ===========================================================================
// 5. 在庫引当と補償処理
// ===========================================================================

async function verifyCheckout(): Promise<void> {
  // --- 5-1 成功したときは在庫が減ったまま残る -----------------------------
  const okState = new ShopState();
  const okGateway = new StubPaymentGateway();

  checkJson('5: 最初の在庫はマスタどおり', okState.stockSnapshot(), MASTER_STOCK);

  const okResult: CheckoutResult = await okState.placeOrder(1, CART_SUCCESS, okGateway);

  checkJson('5: 注文が確定する', okResult, {
    kind: 'ok',
    value: { kind: 'paid', orderId: 1, payableAmount: 3641 },
  });
  checkJson('5: 成功したら在庫は減ったまま', okState.stockSnapshot(), [22, 12, 2, 0, 5]);
  checkString('5: 注文の状態は paid', okState.statusOf(1) ?? '(なし)', 'paid');
  checkJson('5: 決済の記録が残る', okState.paymentOf(1), {
    status: 'succeeded',
    amount: 3641,
    idempotencyKey: 'charge-1',
  });
  checkNumber('5: 課金は1回', okGateway.chargeCount, 1);

  // 二重送信されても同じキーなので課金は増えず、状態も進まない
  await okGateway.charge({ idempotencyKey: 'charge-1', amount: 3641, orderId: '1' });
  checkNumber('5: 再送しても課金は増えない', okGateway.chargeCount, 1);
  checkBoolean('5: すでに paid なら markPaid は何もしない', okState.markPaid(1, 'charge-1'), false);
  checkBoolean('5: paid の注文は cancelOrder で戻せない', okState.cancelOrder(1), false);
  checkJson('5: 二重の補償が起きていない', okState.stockSnapshot(), [22, 12, 2, 0, 5]);

  // --- 5-2 カードが拒否されたら在庫が戻る（補償処理） ---------------------
  const declinedState = new ShopState();
  const declinedGateway = new StubPaymentGateway();
  const declinedResult = await declinedState.placeOrder(1, CART_DECLINED, declinedGateway);

  checkJson('5: 拒否されたら失敗が返る', declinedResult, {
    kind: 'error',
    error: { kind: 'payment_declined', orderId: 1, reason: 'card_declined' },
  });
  checkJson('5: 在庫がマスタの値に戻る', declinedState.stockSnapshot(), MASTER_STOCK);
  checkString('5: 注文は cancelled になる', declinedState.statusOf(1) ?? '(なし)', 'cancelled');
  checkNumber('5: 注文の記録自体は残る（消さない）', declinedState.orderCount(), 1);
  checkString(
    '5: 失敗の説明',
    declinedResult.kind === 'error' ? describeCheckoutFailure(declinedResult.error) : '(成功)',
    'お支払いを完了できませんでした。注文は取り消し、在庫はお戻ししました'
  );

  // --- 5-3 応答が返らないときは在庫を保持して Webhook を待つ --------------
  const pendingState = new ShopState();
  const pendingGateway = new StubPaymentGateway();
  const pendingResult = await pendingState.placeOrder(1, CART_TIMEOUT, pendingGateway, 1_000);

  checkJson('5: 応答なしでも注文は作られる', pendingResult, {
    kind: 'ok',
    value: { kind: 'pending', orderId: 1 },
  });
  checkJson('5: 在庫は引き当てたまま', pendingState.stockSnapshot(), [20, 8, 1, 0, 5]);
  checkString('5: 注文は pending のまま', pendingState.statusOf(1) ?? '(なし)', 'pending');

  // 待つのをやめる時刻の境界
  checkBoolean(
    '5: 15分未満はまだ待つ',
    isStalePending({ status: 'pending', createdAt: 1_000 }, 1_000 + PENDING_ORDER_TTL_MS - 1),
    false
  );
  checkBoolean(
    '5: ちょうど15分で打ち切る',
    isStalePending({ status: 'pending', createdAt: 1_000 }, 1_000 + PENDING_ORDER_TTL_MS),
    true
  );
  checkBoolean(
    '5: paid の注文は掃除の対象にしない',
    isStalePending({ status: 'paid', createdAt: 0 }, PENDING_ORDER_TTL_MS * 10),
    false
  );
  checkNumber(
    '5: 掃除で1件取り消す',
    pendingState.cancelStalePending(1_000 + PENDING_ORDER_TTL_MS),
    1
  );
  checkJson('5: 掃除でも在庫がマスタの値に戻る', pendingState.stockSnapshot(), MASTER_STOCK);
  checkNumber(
    '5: 2回目の掃除では何も起きない',
    pendingState.cancelStalePending(1_000 + PENDING_ORDER_TTL_MS * 5),
    0
  );

  // --- 5-4 在庫が足りないときは1つも減らさない ---------------------------
  const shortState = new ShopState();
  const shortGateway = new StubPaymentGateway();
  const outOfStock = await shortState.placeOrder(
    1,
    buildCartLines([{ productId: 4, quantity: 1 }]),
    shortGateway
  );

  checkJson('5: 在庫切れの商品は買えない', outOfStock, {
    kind: 'error',
    error: { kind: 'stock_conflict', productName: 'リネンのふきん' },
  });
  checkNumber('5: 注文は作られない', shortState.orderCount(), 0);
  checkNumber('5: 決済も呼ばれない', shortGateway.chargeCount, 0);
  checkJson('5: 在庫は変わらない', shortState.stockSnapshot(), MASTER_STOCK);

  // 買える商品と買えない商品が混ざった場合、買える側も減らさない
  const mixed = await shortState.placeOrder(
    1,
    buildCartLines([
      { productId: 1, quantity: 1 },
      { productId: 4, quantity: 1 },
    ]),
    shortGateway
  );

  checkJson('5: 混在したときも失敗する', mixed, {
    kind: 'error',
    error: { kind: 'stock_conflict', productName: 'リネンのふきん' },
  });
  checkJson('5: 石けんの在庫も減っていない', shortState.stockSnapshot(), MASTER_STOCK);

  // 在庫ぴったりは買える。1つ多いと買えない
  const exactState = new ShopState();
  const exactGateway = new StubPaymentGateway();

  checkJson(
    '5: 在庫を超える数量は買えない',
    await exactState.placeOrder(1, buildCartLines([{ productId: 3, quantity: 4 }]), exactGateway),
    { kind: 'error', error: { kind: 'stock_conflict', productName: 'マグカップ' } }
  );
  checkJson(
    '5: 在庫ぴったりは買える',
    await exactState.placeOrder(1, buildCartLines([{ productId: 3, quantity: 3 }]), exactGateway),
    { kind: 'ok', value: { kind: 'paid', orderId: 1, payableAmount: 7755 } }
  );
  checkJson('5: 在庫は0になる', exactState.stockSnapshot(), [24, 12, 0, 0, 5]);

  // --- 5-5 数量とカートの検証は在庫を触る前に行う ------------------------
  const guardState = new ShopState();
  const guardGateway = new StubPaymentGateway();

  checkJson('5: 空のカートは注文できない', await guardState.placeOrder(1, [], guardGateway), {
    kind: 'error',
    error: { kind: 'empty_cart' },
  });
  checkJson(
    '5: 数量0は注文できない',
    await guardState.placeOrder(1, buildCartLines([{ productId: 1, quantity: 0 }]), guardGateway),
    {
      kind: 'error',
      error: { kind: 'invalid_quantity', productName: 'ラベンダーの石けん', quantity: 0 },
    }
  );
  checkJson(
    '5: 上限を超える数量は注文できない',
    await guardState.placeOrder(1, buildCartLines([{ productId: 1, quantity: 11 }]), guardGateway),
    {
      kind: 'error',
      error: { kind: 'invalid_quantity', productName: 'ラベンダーの石けん', quantity: 11 },
    }
  );
  checkJson(
    '5: 小数の数量は注文できない',
    await guardState.placeOrder(1, buildCartLines([{ productId: 1, quantity: 1.5 }]), guardGateway),
    {
      kind: 'error',
      error: { kind: 'invalid_quantity', productName: 'ラベンダーの石けん', quantity: 1.5 },
    }
  );
  checkNumber('5: どれも注文を作らない', guardState.orderCount(), 0);
  checkNumber('5: どれも決済を呼ばない', guardGateway.chargeCount, 0);
  checkJson('5: 在庫も動かない', guardState.stockSnapshot(), MASTER_STOCK);
}

// ===========================================================================
// 6. 注文ステータスの遷移
// ===========================================================================

const TRANSITION_CASES: readonly { from: OrderStatus; to: OrderStatus; allowed: boolean }[] = [
  { from: 'pending', to: 'paid', allowed: true },
  { from: 'pending', to: 'cancelled', allowed: true },
  { from: 'pending', to: 'shipped', allowed: false },
  { from: 'pending', to: 'pending', allowed: false },
  { from: 'paid', to: 'shipped', allowed: true },
  { from: 'paid', to: 'cancelled', allowed: true },
  { from: 'paid', to: 'pending', allowed: false },
  { from: 'paid', to: 'paid', allowed: false },
  { from: 'shipped', to: 'pending', allowed: false },
  { from: 'shipped', to: 'paid', allowed: false },
  { from: 'shipped', to: 'shipped', allowed: false },
  { from: 'shipped', to: 'cancelled', allowed: false },
  { from: 'cancelled', to: 'pending', allowed: false },
  { from: 'cancelled', to: 'paid', allowed: false },
  { from: 'cancelled', to: 'shipped', allowed: false },
  { from: 'cancelled', to: 'cancelled', allowed: false },
];

checkNumber('6: 遷移の組み合わせは4×4', TRANSITION_CASES.length, ORDER_STATUSES.length ** 2);

for (const testCase of TRANSITION_CASES) {
  checkBoolean(
    `6: ${testCase.from} → ${testCase.to}`,
    canTransitionTo(testCase.from, testCase.to),
    testCase.allowed
  );
}

checkBoolean('6: pending は取り消せる', canCancelOrder('pending'), true);
checkBoolean('6: paid も取り消せる', canCancelOrder('paid'), true);
checkBoolean('6: shipped は取り消せない', canCancelOrder('shipped'), false);
checkBoolean('6: cancelled は取り消せない', canCancelOrder('cancelled'), false);
checkBoolean('6: shipped は終着点', isSettled('shipped'), true);
checkBoolean('6: cancelled は終着点', isSettled('cancelled'), true);
checkBoolean('6: pending は終着点ではない', isSettled('pending'), false);
checkBoolean('6: paid は終着点ではない', isSettled('paid'), false);

checkString('6: pending の表示', describeOrderStatus('pending'), 'お支払いの確認中');
checkString('6: paid の表示', describeOrderStatus('paid'), 'お支払い済み');
checkString('6: shipped の表示', describeOrderStatus('shipped'), '発送済み');
checkString('6: cancelled の表示', describeOrderStatus('cancelled'), 'キャンセル');

checkString('6: DB の文字列を型に戻す', parseOrderStatus('shipped'), 'shipped');
checkString('6: 知らない値は pending に寄せる', parseOrderStatus('refunded'), 'pending');

// ===========================================================================
// 7. Webhook の重複受信
// ===========================================================================

async function verifyWebhookHandling(): Promise<void> {
  const state = new ShopState();
  const gateway = new StubPaymentGateway();

  await state.placeOrder(1, CART_TIMEOUT, gateway, 0);
  checkString('7: 前提として pending', state.statusOf(1) ?? '(なし)', 'pending');

  const first = state.applyWebhookEvent(SUCCEEDED_EVENT);

  checkJson('7: 1回目は適用される', first, { kind: 'applied', orderId: 1, status: 'paid' });
  checkString('7: 状態が paid になる', state.statusOf(1) ?? '(なし)', 'paid');
  checkJson('7: 在庫は引き当てたまま', state.stockSnapshot(), [20, 8, 1, 0, 5]);

  const second = state.applyWebhookEvent(SUCCEEDED_EVENT);

  checkJson('7: 同じ eventId の2回目は重複', second, {
    kind: 'duplicate',
    eventId: 'evt_20260901_0001',
  });
  checkString('7: 状態は変わらない', state.statusOf(1) ?? '(なし)', 'paid');
  checkJson('7: 在庫も変わらない', state.stockSnapshot(), [20, 8, 1, 0, 5]);

  // 別の eventId でも、決着済みの注文には何もしない
  const late = state.applyWebhookEvent({ ...SUCCEEDED_EVENT, eventId: 'evt_late' });

  checkJson('7: 決着済みの注文への通知', late, {
    kind: 'already_settled',
    orderId: 1,
    status: 'paid',
  });

  // 知らない注文
  checkJson(
    '7: 知らない注文への通知',
    state.applyWebhookEvent({ ...SUCCEEDED_EVENT, eventId: 'evt_unknown', orderId: 99 }),
    { kind: 'unknown_order', orderId: 99 }
  );

  // 金額が合わない通知は適用しない
  const mismatchState = new ShopState();
  const mismatchGateway = new StubPaymentGateway();

  await mismatchState.placeOrder(1, CART_TIMEOUT, mismatchGateway, 0);

  const mismatch = mismatchState.applyWebhookEvent({
    ...SUCCEEDED_EVENT,
    eventId: 'evt_mismatch',
    amount: 9999,
  });

  checkJson('7: 金額が合わない通知', mismatch, {
    kind: 'amount_mismatch',
    orderId: 1,
    expected: 15202,
    received: 9999,
  });
  checkString('7: 状態は pending のまま', mismatchState.statusOf(1) ?? '(なし)', 'pending');

  // 失敗の通知が来たら、在庫を戻して取り消す
  const failedState = new ShopState();
  const failedGateway = new StubPaymentGateway();

  await failedState.placeOrder(1, CART_TIMEOUT, failedGateway, 0);

  const failedOutcome = failedState.applyWebhookEvent({
    eventId: 'evt_failed',
    type: 'payment.failed',
    paymentId: 'pay_charge-1',
    orderId: 1,
    amount: 15202,
  });

  checkJson('7: 失敗の通知は取り消しになる', failedOutcome, {
    kind: 'applied',
    orderId: 1,
    status: 'cancelled',
  });
  checkJson('7: 在庫がマスタの値に戻る', failedState.stockSnapshot(), MASTER_STOCK);
  checkJson('7: 決済の記録も failed になる', failedState.paymentOf(1), {
    status: 'failed',
    amount: 15202,
    idempotencyKey: 'charge-1',
  });

  // 応答（HTTP ステータス）の割り当て
  checkNumber('7: 適用したら200', statusForOutcome(first), 200);
  checkNumber('7: 重複でも200（再送を止めるため）', statusForOutcome(second), 200);
  checkNumber('7: 決着済みでも200', statusForOutcome(late), 200);
  checkNumber('7: 知らない注文は404', statusForOutcome({ kind: 'unknown_order', orderId: 99 }), 404);
  checkNumber('7: 金額の食い違いは409', statusForOutcome(mismatch), 409);
}

// ===========================================================================
// 8. IDOR（他人の注文が1件も見えない）
// ===========================================================================

const DEMO_USER: SessionUser = {
  id: 1,
  email: 'demo@example.com',
  name: 'デモユーザー',
  role: 'user',
};
const ADMIN_USER: SessionUser = {
  id: 2,
  email: 'admin@example.com',
  name: '店長',
  role: 'admin',
};
const OTHER_USER: SessionUser = {
  id: 3,
  email: 'other@example.com',
  name: '別のお客さま',
  role: 'user',
};

async function verifyOrderAccess(): Promise<void> {
  const state = new ShopState();
  const gateway = new StubPaymentGateway();

  // 注文1・2 はデモユーザー、注文3 は別のお客さま
  await state.placeOrder(DEMO_USER.id, CART_SUCCESS, gateway);
  await state.placeOrder(DEMO_USER.id, CART_WITH_SHIPPING, gateway);
  await state.placeOrder(OTHER_USER.id, CART_WITH_SHIPPING, gateway);

  checkNumber('8: 注文は3件', state.orderCount(), 3);

  const users: readonly (SessionUser | undefined)[] = [DEMO_USER, ADMIN_USER, OTHER_USER, undefined];
  const orders = [1, 2, 3];
  const owners: Record<number, number> = { 1: DEMO_USER.id, 2: DEMO_USER.id, 3: OTHER_USER.id };

  // 4人（未ログインを含む）×3注文＝12通りを全部確かめる
  for (const user of users) {
    for (const orderId of orders) {
      const order = { userId: owners[orderId] ?? 0 };
      const expected = user !== undefined && user.id === (owners[orderId] ?? 0);
      const label = user === undefined ? '未ログイン' : user.email;

      checkBoolean(`8: ${label} が注文#${orderId} を見られるか`, canViewOrder(user, order), expected);
    }
  }

  checkNumber('8: デモユーザーの注文は2件', state.ordersFor(DEMO_USER.id).length, 2);
  checkNumber('8: 管理者は自分の注文を1件も持たない', state.ordersFor(ADMIN_USER.id).length, 0);
  checkNumber('8: 別のお客さまの注文は1件', state.ordersFor(OTHER_USER.id).length, 1);

  checkBoolean(
    '8: 他人の注文は取得できない',
    state.findOrderForUser(3, DEMO_USER.id) === undefined,
    true
  );
  checkNumber(
    '8: 自分の注文は取得できる',
    state.findOrderForUser(1, DEMO_USER.id)?.id ?? 0,
    1
  );
  checkBoolean(
    '8: 管理者でもこの入口では他人の注文を見られない',
    state.findOrderForUser(1, ADMIN_USER.id) === undefined,
    true
  );

  // 注文明細の単価は「注文した時点の価格」を写して持っている
  const firstOrder = state.findOrderForUser(1, DEMO_USER.id);

  checkJson(
    '8: 明細には単価が写っている',
    firstOrder?.items ?? [],
    [
      { productId: 1, quantity: 2, unitPrice: 480 },
      { productId: 3, quantity: 1, unitPrice: 2350 },
    ]
  );
  checkNumber(
    '8: 明細の単価×数量の合計は税抜小計と一致する',
    (firstOrder?.items ?? []).reduce((total, item) => total + item.unitPrice * item.quantity, 0),
    3310
  );
}

// ---------------------------------------------------------------------------
// 実行と結果
// ---------------------------------------------------------------------------
async function main(): Promise<void> {
  await verifyIdempotency();
  await verifyCheckout();
  await verifyWebhookHandling();
  await verifyOrderAccess();

  if (failedCount > 0) {
    console.error(`final: ${failedCount} 件の検証に失敗しました`);
    process.exit(1);
  }

  console.log('final: ok');
}

main().catch((error: unknown) => {
  console.error('final: 予期しない例外が発生しました', error);
  process.exit(1);
});
