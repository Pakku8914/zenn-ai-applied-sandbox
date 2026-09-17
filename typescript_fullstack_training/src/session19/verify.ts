// セッション19「テストとコード品質」の検証スクリプト。
//
// この章のコードの大半は vitest のテストとして書かれており、
// verify-all.sh の中で `npx vitest run` が先に走るのでそちらで検証される。
// このファイルは、本文と解答に「数値」「文字列」として書いた期待値が
// 実装と一致しているかを、テストとは独立にもう一度確かめる。
//
// 実行: docker compose exec ts npx tsx src/session19/verify.ts

import { describeLine, isWithinQuantityLimit, toCartLines } from '../session16/cart';
import { buildPaymentSummary, calcShippingFee, resolveDiscountRule } from '../session16/pricing';
import { brokenCartItems, cartItems, products } from '../session16/shop-data';
import type { MemberRank } from '../session16/types';
import { buildReservations, describeShopError, parseQuantity, reserveStock } from '../session18/shop';
import { resolveMemberRank } from './member';
import { buildPaymentSummaryBuggy } from './pricing-buggy';
import { buildStockReportLine, notifyLowStock } from './report';
import { StockShortageError, reserveStockOrThrow } from './stock';
import { mixedCart, requireCatalogItem, requireProduct, soapCart, toteBagCart } from './test-data';
import { placeOrder } from './practice/q5-order';
import {
  calcRemainingForFreeShipping,
  isFreeShipping,
  isFreeShippingBuggy,
} from './practice/q6-shipping';
import { createCatalogLoader, createFailingLoader, withStock } from './practice/q7-checkout';

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
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

/** オブジェクトの中身を JSON にして比べる */
function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ---------------------------------------------------------------------------
// 本文1〜2節：正しい実装とバグ入りの実装の差
// ---------------------------------------------------------------------------
const noDiscount = resolveDiscountRule('none');
const goldDiscount = resolveDiscountRule('gold');

checkJson('本文1節: トートバッグ1点の内訳', buildPaymentSummary(toteBagCart, noDiscount), {
  subtotal: 2800,
  discountAmount: 0,
  discountedTotal: 2800,
  tax: 280,
  totalWithTax: 3080,
  shippingFee: 0,
  payableAmount: 3080,
});

const buggyTote = buildPaymentSummaryBuggy(toteBagCart, noDiscount);
checkNumber('本文1節: バグ入りの送料', buggyTote.shippingFee, 500);
checkNumber('本文1節: バグ入りの支払総額', buggyTote.payableAmount, 3580);

checkJson('本文2節: ゴールド会員の内訳', buildPaymentSummary(mixedCart, goldDiscount), {
  subtotal: 3310,
  discountAmount: 331,
  discountedTotal: 2979,
  tax: 297,
  totalWithTax: 3276,
  shippingFee: 0,
  payableAmount: 3276,
});
checkNumber(
  '本文2節: ゴールド会員でのバグ入りの支払総額',
  buildPaymentSummaryBuggy(mixedCart, goldDiscount).payableAmount,
  3776
);

// 空のカートは「送料500円だけ請求される」。テストを書いて初めて気づく仕様の穴
const emptySummary = buildPaymentSummary([], noDiscount);
checkNumber('本文2節: 空カートの送料', emptySummary.shippingFee, 500);
checkNumber('本文2節: 空カートの支払総額', emptySummary.payableAmount, 500);

// ---------------------------------------------------------------------------
// 本文2節：toCartLines と describeLine
// ---------------------------------------------------------------------------
checkNumber('本文2節: カート2件を変換', toCartLines(cartItems).length, 2);
checkNumber('本文2節: 削除された商品を落とす', toCartLines(brokenCartItems).length, 1);
checkString(
  '本文2節: 明細の表示',
  describeLine({ product: requireProduct(3), quantity: 2 }),
  'マグカップ × 2点 = 4700円'
);

// ---------------------------------------------------------------------------
// 本文3節：境界値の表
// ---------------------------------------------------------------------------
const shippingCases: { totalWithTax: number; expected: number }[] = [
  { totalWithTax: 0, expected: 500 },
  { totalWithTax: 2999, expected: 500 },
  { totalWithTax: 3000, expected: 0 },
  { totalWithTax: 3001, expected: 0 },
];

for (const { totalWithTax, expected } of shippingCases) {
  checkNumber(`本文3節: 送料（税込${totalWithTax}円）`, calcShippingFee(totalWithTax), expected);
}

const quantityCases: { quantity: number; expected: boolean }[] = [
  { quantity: 0, expected: false },
  { quantity: 1, expected: true },
  { quantity: 10, expected: true },
  { quantity: 11, expected: false },
];

for (const { quantity, expected } of quantityCases) {
  checkBoolean(
    `本文3節: 数量の上限（${quantity}点）`,
    isWithinQuantityLimit({ product: requireProduct(1), quantity }),
    expected
  );
}

// ---------------------------------------------------------------------------
// 本文5節：例外を投げる版と Result を返す版
// ---------------------------------------------------------------------------
checkJson('本文5節: 例外版の成功', reserveStockOrThrow(requireCatalogItem(3), 2), {
  productId: 3,
  productName: 'マグカップ',
  quantity: 2,
  lineTotal: 4700,
});
checkNumber(
  '本文5節: 在庫ちょうどの数量',
  reserveStockOrThrow(requireCatalogItem(3), 3).lineTotal,
  7050
);

let shortageName = '';
let shortageMessage = '';

try {
  reserveStockOrThrow(requireCatalogItem(4), 1);
} catch (error) {
  if (error instanceof StockShortageError) {
    shortageName = error.name;
    shortageMessage = error.message;
  }
}

checkString('本文5節: エラーの name', shortageName, 'StockShortageError');
checkString(
  '本文5節: エラーの message',
  shortageMessage,
  'リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）'
);

let rangeErrorSeen = false;

try {
  reserveStockOrThrow(requireCatalogItem(1), 0);
} catch (error) {
  rangeErrorSeen = error instanceof RangeError;
}
checkBoolean('本文5節: 数量0は RangeError', rangeErrorSeen, true);

checkJson('本文5節: Result 版の成功', reserveStock(requireCatalogItem(3), 2), {
  kind: 'ok',
  value: { productId: 3, productName: 'マグカップ', quantity: 2, lineTotal: 4700 },
});
checkJson('本文5節: Result 版の失敗', reserveStock(requireCatalogItem(4), 2), {
  kind: 'error',
  error: {
    kind: 'out_of_stock',
    productName: 'リネンのふきん',
    requested: 2,
    available: 0,
  },
});

const quantityInputCases: { input: string; expected: string }[] = [
  { input: '0', expected: 'error' },
  { input: '1', expected: 'ok' },
  { input: '10', expected: 'ok' },
  { input: '11', expected: 'error' },
  { input: '1.5', expected: 'error' },
  { input: '', expected: 'error' },
];

for (const { input, expected } of quantityInputCases) {
  checkString(`本文5節: parseQuantity("${input}")`, parseQuantity(input).kind, expected);
}

const invalidQuantity = parseQuantity('abc');

if (invalidQuantity.kind === 'error') {
  checkString(
    '本文5節: 失敗の説明文',
    describeShopError(invalidQuantity.error),
    '数量は整数で入力してください（受け取った値: abc）'
  );
} else {
  console.error('NG: parseQuantity("abc") が成功してしまいました');
  failedCount += 1;
}

// ---------------------------------------------------------------------------
// 本文6節：通知と、時刻を引数で受け取るレポート
// ---------------------------------------------------------------------------
const notified: string[] = [];
const lowStockCount = notifyLowStock(products, 3, (message) => {
  notified.push(message);
});

checkNumber('本文6節: 通知した件数', lowStockCount, 2);
checkString(
  '本文6節: 通知の内容',
  notified.join('\n'),
  'マグカップの在庫が残り3点です\nリネンのふきんの在庫が残り0点です'
);
checkString(
  '本文6節: 在庫レポートの1行',
  buildStockReportLine(requireProduct(3), new Date('2026-08-27T09:00:00Z')),
  '[2026-08-27] マグカップ: 在庫3点'
);

// ---------------------------------------------------------------------------
// 問題1：石けん3点のカート
// ---------------------------------------------------------------------------
checkJson('問題1: 割引なし', buildPaymentSummary(soapCart, noDiscount), {
  subtotal: 1440,
  discountAmount: 0,
  discountedTotal: 1440,
  tax: 144,
  totalWithTax: 1584,
  shippingFee: 500,
  payableAmount: 2084,
});
checkNumber(
  '問題1: ブロンズ会員',
  buildPaymentSummary(soapCart, resolveDiscountRule('bronze')).payableAmount,
  2036
);

// ---------------------------------------------------------------------------
// 問題2：会員ランクのしきい値
// ---------------------------------------------------------------------------
const rankCases: { totalSpent: number; expected: MemberRank }[] = [
  { totalSpent: 0, expected: 'none' },
  { totalSpent: 4999, expected: 'none' },
  { totalSpent: 5000, expected: 'bronze' },
  { totalSpent: 19999, expected: 'bronze' },
  { totalSpent: 20000, expected: 'silver' },
  { totalSpent: 49999, expected: 'silver' },
  { totalSpent: 50000, expected: 'gold' },
];

for (const { totalSpent, expected } of rankCases) {
  checkString(`問題2: 累計${totalSpent}円のランク`, resolveMemberRank(totalSpent), expected);
}

const discountCases: { rank: MemberRank; expected: number }[] = [
  { rank: 'gold', expected: 1000 },
  { rank: 'silver', expected: 500 },
  { rank: 'bronze', expected: 300 },
  { rank: 'none', expected: 0 },
];

for (const { rank, expected } of discountCases) {
  checkNumber(`問題2: ${rank} の割引額`, resolveDiscountRule(rank)(10000), expected);
}

// ---------------------------------------------------------------------------
// 問題5：注文の確定と通知
// ---------------------------------------------------------------------------
const orderMessages: string[] = [];
const placed = placeOrder(toteBagCart, 'none', (message) => {
  orderMessages.push(message);
});

checkString('問題5: 成功したか', placed.kind, 'ok');
checkString('問題5: 通知の内容', orderMessages.join('\n'), '注文を受け付けました（3080円）');

const goldMessages: string[] = [];
placeOrder(toteBagCart, 'gold', (message) => {
  goldMessages.push(message);
});
checkString(
  '問題5: ゴールド会員の通知（割引で送料無料を失う）',
  goldMessages.join('\n'),
  '注文を受け付けました（3272円）'
);

const emptyMessages: string[] = [];
const emptyResult = placeOrder([], 'none', (message) => {
  emptyMessages.push(message);
});
checkJson('問題5: 空カートは失敗', emptyResult, { kind: 'error', message: 'カートが空です' });
checkNumber('問題5: 失敗時は通知しない', emptyMessages.length, 0);

const overLimit = placeOrder([{ product: requireProduct(1), quantity: 11 }], 'none', () => {
  // 呼ばれないことを確かめたいので何もしない
});
checkJson('問題5: 数量超過は失敗', overLimit, {
  kind: 'error',
  message: '数量が上限を超えています: ラベンダーの石けん',
});

// ---------------------------------------------------------------------------
// 問題6：カバレッジ100%でも残るバグ
// ---------------------------------------------------------------------------
checkBoolean('問題6: 正しい実装は3000円ちょうどで無料', isFreeShipping(3000), true);
checkBoolean('問題6: バグ入りは3000円ちょうどで有料', isFreeShippingBuggy(3000), false);
checkBoolean('問題6: 2999円はどちらも有料', isFreeShipping(2999), false);
checkBoolean('問題6: 3001円はどちらも無料', isFreeShippingBuggy(3001), true);

const remainingCases: { totalWithTax: number; expected: number }[] = [
  { totalWithTax: 0, expected: 3000 },
  { totalWithTax: 2999, expected: 1 },
  { totalWithTax: 3000, expected: 0 },
  { totalWithTax: 4000, expected: 0 },
];

for (const { totalWithTax, expected } of remainingCases) {
  checkNumber(
    `問題6: 無料まであと（税込${totalWithTax}円）`,
    calcRemainingForFreeShipping(totalWithTax),
    expected
  );
}

// ---------------------------------------------------------------------------
// 問題7：buildReservations（loader を差し替えて成功・失敗を作る）
// ---------------------------------------------------------------------------
checkJson(
  '問題7: すべて成功',
  await buildReservations(
    [
      { productId: 1, quantityInput: '2' },
      { productId: 3, quantityInput: '1' },
    ],
    createCatalogLoader()
  ),
  {
    kind: 'ok',
    value: [
      { productId: 1, productName: 'ラベンダーの石けん', quantity: 2, lineTotal: 960 },
      { productId: 3, productName: 'マグカップ', quantity: 1, lineTotal: 2350 },
    ],
  }
);

checkJson('問題7: リクエストが空', await buildReservations([], createCatalogLoader()), {
  kind: 'ok',
  value: [],
});

const collected = await buildReservations(
  [
    { productId: 1, quantityInput: '2' },
    { productId: 4, quantityInput: '1' },
    { productId: 99, quantityInput: '1' },
    { productId: 3, quantityInput: '0' },
  ],
  createCatalogLoader()
);

if (collected.kind === 'error') {
  checkString(
    '問題7: 失敗を集める',
    collected.error.map((error) => error.kind).join(','),
    'out_of_stock,product_not_found,quantity_out_of_range'
  );

  const firstError = collected.error[0];

  if (firstError === undefined) {
    console.error('NG: 失敗が1件も集まりませんでした');
    failedCount += 1;
  } else {
    checkString(
      '問題7: 在庫不足の説明文',
      describeShopError(firstError),
      'リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）'
    );
  }
} else {
  console.error('NG: 失敗するはずのリクエストが成功しました');
  failedCount += 1;
}

checkJson(
  '問題7: 在庫を差し替えて在庫切れを再現',
  await buildReservations(
    [{ productId: 1, quantityInput: '2' }],
    createCatalogLoader(withStock(1, 1))
  ),
  {
    kind: 'error',
    error: [
      { kind: 'out_of_stock', productName: 'ラベンダーの石けん', requested: 2, available: 1 },
    ],
  }
);

checkJson(
  '問題7: 読み込みの失敗',
  await buildReservations(
    [{ productId: 1, quantityInput: '1' }],
    createFailingLoader('fixture が見つかりません')
  ),
  {
    kind: 'error',
    error: [{ kind: 'catalog_unavailable', reason: 'fixture が見つかりません' }],
  }
);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session19: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session19: ok');
