// セッション22「Reactの基礎」の検証スクリプト。
//
// この章の部品（.tsx）は web フォルダ側にあり、src 側の tsconfig には DOM も React も
// 無いため、ここから web のモジュールを import することはできない。
// そこで、章で「画面の外に切り出した純粋なロジック」だけを同じ実装としてこのファイルに置き、
// 本文・練習問題・解答に書いた期待値と一致するかを確かめる。
// 対応する web 側の実装は lib フォルダの cart.ts / format.ts / pricing.ts。
// 部品そのものは verify-all.sh の最後にある web の型チェックと next build が検証する。
//
// 実行: docker compose exec ts npx tsx src/session22/verify.ts

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

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ---------------------------------------------------------------------------
// 検証用のデータ。
// カートの計算と表示は id / name / price / stock しか見ないので、description と
// imageUrl を省いた ProductSummary で確かめる（値はマスタと同じ）。
// web 側の CartLine は7フィールドの Product をそのまま使っている。
// ---------------------------------------------------------------------------
type ProductSummary = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryId: number;
};

type CartLine = {
  product: ProductSummary;
  quantity: number;
};

const PRODUCTS: readonly ProductSummary[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

function productAt(id: number): ProductSummary {
  const found = PRODUCTS.find((product) => product.id === id);

  if (found === undefined) {
    throw new Error(`検証用データに商品 ${id} がありません`);
  }

  return found;
}

const SOAP = productAt(1);
const HAND_CREAM = productAt(2);
const MUG = productAt(3);
const LINEN_CLOTH = productAt(4);
const TOTE_BAG = productAt(5);

/** 明細を「商品id:数量」の並びにして比較しやすくする */
function toLineList(lines: readonly CartLine[]): string {
  return lines.map((line) => `${line.product.id}:${line.quantity}`).join(',');
}

// ---------------------------------------------------------------------------
// 本文2節：表示のための整形（web 側の lib/format.ts と同じ実装）
// ---------------------------------------------------------------------------
function formatYen(amount: number): string {
  const sign = amount < 0 ? '-' : '';
  const digits = String(Math.abs(amount));
  const headLength = digits.length % 3 === 0 ? 3 : digits.length % 3;
  const groups: string[] = [digits.slice(0, headLength)];

  for (let start = headLength; start < digits.length; start += 3) {
    groups.push(digits.slice(start, start + 3));
  }

  return `${sign}${groups.join(',')}円`;
}

const yenCases: { amount: number; expected: string }[] = [
  { amount: 0, expected: '0円' },
  { amount: 480, expected: '480円' },
  { amount: 990, expected: '990円' },
  { amount: 1800, expected: '1,800円' },
  { amount: 2350, expected: '2,350円' },
  { amount: 3080, expected: '3,080円' },
  { amount: 11520, expected: '11,520円' },
  { amount: 100000, expected: '100,000円' },
  { amount: 1234567, expected: '1,234,567円' },
  { amount: -500, expected: '-500円' },
];

for (const { amount, expected } of yenCases) {
  checkString(`本文2節: formatYen(${amount})`, formatYen(amount), expected);
}

// ---------------------------------------------------------------------------
// 本文3節：key に使う値の組み立て（web 側の lib/format.ts と同じ実装）
// ---------------------------------------------------------------------------
function cartLineKey(line: CartLine): string {
  return `line-${line.product.id}`;
}

checkString('本文3節: cartLineKey（マグカップ）', cartLineKey({ product: MUG, quantity: 2 }), 'line-3');
checkString('本文3節: cartLineKey（石けん）', cartLineKey({ product: SOAP, quantity: 1 }), 'line-1');

// ---------------------------------------------------------------------------
// 本文5節：カートの状態を更新する純粋関数（web 側の lib/cart.ts と同じ実装）
// ---------------------------------------------------------------------------
const MAX_CART_QUANTITY = 10;

function clampQuantity(quantity: number): number {
  const rounded = Math.floor(quantity);

  return Math.min(Math.max(rounded, 1), MAX_CART_QUANTITY);
}

function addLine(
  lines: readonly CartLine[],
  product: ProductSummary,
  quantity: number = 1
): CartLine[] {
  const exists = lines.some((line) => line.product.id === product.id);

  if (!exists) {
    return [...lines, { product, quantity: clampQuantity(quantity) }];
  }

  return lines.map((line) =>
    line.product.id === product.id
      ? { ...line, quantity: clampQuantity(line.quantity + quantity) }
      : line
  );
}

function changeQuantity(
  lines: readonly CartLine[],
  productId: number,
  quantity: number
): CartLine[] {
  return lines.map((line) =>
    line.product.id === productId ? { ...line, quantity: clampQuantity(quantity) } : line
  );
}

function removeLine(lines: readonly CartLine[], productId: number): CartLine[] {
  return lines.filter((line) => line.product.id !== productId);
}

function calcTotalQuantity(lines: readonly CartLine[]): number {
  return lines.reduce((total, line) => total + line.quantity, 0);
}

// 数量を丸める規則
const clampCases: { input: number; expected: number }[] = [
  { input: 1, expected: 1 },
  { input: 10, expected: 10 },
  { input: 11, expected: 10 },
  { input: 99, expected: 10 },
  { input: 0, expected: 1 },
  { input: -5, expected: 1 },
  { input: 2.7, expected: 2 },
];

for (const { input, expected } of clampCases) {
  checkNumber(`本文5節: clampQuantity(${input})`, clampQuantity(input), expected);
}

// 空のカートから順に操作する
const step1 = addLine([], SOAP);
const step2 = addLine(step1, SOAP);
const step3 = addLine(step2, MUG, 2);
const step4 = changeQuantity(step3, 1, 4);
const step5 = removeLine(step4, 3);

checkString('本文5節: 石けんを1点追加', toLineList(step1), '1:1');
checkString('本文5節: 同じ商品は1明細にまとめる', toLineList(step2), '1:2');
checkString('本文5節: 別の商品は明細が増える', toLineList(step3), '1:2,3:2');
checkString('本文5節: 数量を4に変更', toLineList(step4), '1:4,3:2');
checkString('本文5節: マグカップの明細を削除', toLineList(step5), '1:4');

// イミュータブル更新：元の配列は書き換わっていない
checkNumber('本文5節: 元の配列の長さは変わらない', step1.length, 1);
checkString('本文5節: 元の配列の中身も変わらない', toLineList(step1), '1:1');
checkBoolean(
  '本文5節: 変更していない明細は同じオブジェクトを使い回す',
  Object.is(step3[1], step4[1]),
  true
);

// 上限（1明細10点まで）
const overflow = addLine(addLine([], SOAP, 8), SOAP, 5);

checkString('本文5節: 上限を超える追加は10点で止まる', toLineList(overflow), '1:10');
checkString('本文5節: 0点の追加は1点として扱う', toLineList(addLine([], MUG, 0)), '3:1');
checkString(
  '本文5節: 存在しない商品の数量変更は何も起きない',
  toLineList(changeQuantity(step3, 99, 5)),
  '1:2,3:2'
);
checkString(
  '本文5節: 存在しない商品の削除は何も起きない',
  toLineList(removeLine(step3, 99)),
  '1:2,3:2'
);
checkNumber('本文5節: 合計点数', calcTotalQuantity(step3), 4);
checkNumber('本文5節: 空のカートの合計点数', calcTotalQuantity([]), 0);

// ---------------------------------------------------------------------------
// 本文5節：支払総額の内訳（web 側の lib/pricing.ts と同じ実装）
// 手順と丸めは本書共通。送料の判定は「税込商品合計」で行う。
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;

type DiscountRule = (subtotal: number) => number;

const noDiscount: DiscountRule = () => 0;

type PaymentSummary = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

function calcLineTotal(price: number, quantity: number): number {
  return price * quantity;
}

function calcSubtotal(lines: readonly CartLine[]): number {
  return lines.reduce(
    (total, line) => total + calcLineTotal(line.product.price, line.quantity),
    0
  );
}

function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

function calcRemainingForFreeShipping(totalWithTax: number): number {
  return Math.max(0, FREE_SHIPPING_THRESHOLD - totalWithTax);
}

function buildPaymentSummary(
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

// 石けん2点 + マグカップ1点
checkJson('本文5節: 石けん2点とマグカップ1点', buildPaymentSummary([
  { product: SOAP, quantity: 2 },
  { product: MUG, quantity: 1 },
]), {
  subtotal: 3310,
  discountAmount: 0,
  discountedTotal: 3310,
  tax: 331,
  totalWithTax: 3641,
  shippingFee: 0,
  payableAmount: 3641,
});

// 石けん2点だけ（送料がかかる）
checkJson('本文5節: 石けん2点だけ', buildPaymentSummary([{ product: SOAP, quantity: 2 }]), {
  subtotal: 960,
  discountAmount: 0,
  discountedTotal: 960,
  tax: 96,
  totalWithTax: 1056,
  shippingFee: 500,
  payableAmount: 1556,
});

// トートバッグ1点：税抜2800円（3000円未満）だが、税込3080円なので送料は無料
checkJson('本文5節: 送料は税込商品合計で判定する', buildPaymentSummary([
  { product: TOTE_BAG, quantity: 1 },
]), {
  subtotal: 2800,
  discountAmount: 0,
  discountedTotal: 2800,
  tax: 280,
  totalWithTax: 3080,
  shippingFee: 0,
  payableAmount: 3080,
});

// 空のカート：計算そのものは送料500円を返す。空のときに内訳を出さないのは表示側の判断
checkNumber('本文5節: 空のカートの支払総額', buildPaymentSummary([]).payableAmount, 500);

// 割引ルールを渡した場合（石けん10点で10%割引）
checkJson('本文5節: 10%割引を適用', buildPaymentSummary(
  [{ product: SOAP, quantity: 10 }],
  (subtotal) => Math.floor((subtotal * 10) / 100)
), {
  subtotal: 4800,
  discountAmount: 480,
  discountedTotal: 4320,
  tax: 432,
  totalWithTax: 4752,
  shippingFee: 0,
  payableAmount: 4752,
});

const shippingCases: { totalWithTax: number; fee: number; remaining: number }[] = [
  { totalWithTax: 0, fee: 500, remaining: 3000 },
  { totalWithTax: 1056, fee: 500, remaining: 1944 },
  { totalWithTax: 2999, fee: 500, remaining: 1 },
  { totalWithTax: 3000, fee: 0, remaining: 0 },
  { totalWithTax: 3080, fee: 0, remaining: 0 },
];

for (const { totalWithTax, fee, remaining } of shippingCases) {
  checkNumber(`本文5節: 送料（税込${totalWithTax}円）`, calcShippingFee(totalWithTax), fee);
  checkNumber(
    `本文5節: 無料まであと（税込${totalWithTax}円）`,
    calcRemainingForFreeShipping(totalWithTax),
    remaining
  );
}

// ---------------------------------------------------------------------------
// 問題2：在庫の表示ラベル
// ---------------------------------------------------------------------------
const LOW_STOCK_THRESHOLD = 5;

function stockLabel(stock: number): string {
  if (stock <= 0) {
    return '在庫切れ';
  }

  if (stock <= LOW_STOCK_THRESHOLD) {
    return `残り${stock}点`;
  }

  return '在庫あり';
}

const stockCases: { stock: number; expected: string }[] = [
  { stock: 24, expected: '在庫あり' },
  { stock: 12, expected: '在庫あり' },
  { stock: 6, expected: '在庫あり' },
  { stock: 5, expected: '残り5点' },
  { stock: 4, expected: '残り4点' },
  { stock: 3, expected: '残り3点' },
  { stock: 1, expected: '残り1点' },
  { stock: 0, expected: '在庫切れ' },
  { stock: -1, expected: '在庫切れ' },
];

for (const { stock, expected } of stockCases) {
  checkString(`問題2: stockLabel(${stock})`, stockLabel(stock), expected);
}

// マスタの5件に当てはめた結果
checkString(
  '問題2: マスタ5件のラベル',
  PRODUCTS.map((product) => stockLabel(product.stock)).join(' / '),
  '在庫あり / 在庫あり / 残り3点 / 在庫切れ / 残り5点'
);

// ---------------------------------------------------------------------------
// 問題4：入力欄の文字列を数量として解釈する
// ---------------------------------------------------------------------------
function parseQuantity(raw: string): number | null {
  const trimmed = raw.trim();

  if (!/^[1-9][0-9]*$/.test(trimmed)) {
    return null;
  }

  const quantity = Number(trimmed);

  return quantity <= MAX_CART_QUANTITY ? quantity : null;
}

function buildQuantityOptions(stock: number): number[] {
  const max = Math.min(Math.max(stock, 1), MAX_CART_QUANTITY);

  return Array.from({ length: max }, (_, index) => index + 1);
}

const quantityCases: { raw: string; expected: number | null }[] = [
  { raw: '1', expected: 1 },
  { raw: '10', expected: 10 },
  { raw: ' 2 ', expected: 2 },
  { raw: '11', expected: null },
  { raw: '0', expected: null },
  { raw: '-1', expected: null },
  { raw: '02', expected: null },
  { raw: '2.5', expected: null },
  { raw: 'abc', expected: null },
  { raw: '', expected: null },
];

for (const { raw, expected } of quantityCases) {
  checkString(`問題4: parseQuantity("${raw}")`, String(parseQuantity(raw)), String(expected));
}

checkJson('問題4: 在庫3点の選択肢', buildQuantityOptions(MUG.stock), [1, 2, 3]);
checkJson('問題4: 在庫5点の選択肢', buildQuantityOptions(TOTE_BAG.stock), [1, 2, 3, 4, 5]);
checkJson(
  '問題4: 在庫24点でも上限は10',
  buildQuantityOptions(SOAP.stock),
  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
);
checkJson('問題4: 在庫0点でも空にはしない', buildQuantityOptions(LINEN_CLOTH.stock), [1]);

// ---------------------------------------------------------------------------
// 問題6：明細から決まる値（state にせず、そのつど計算する）
// ---------------------------------------------------------------------------
const sampleLines: readonly CartLine[] = [
  { product: SOAP, quantity: 2 },
  { product: HAND_CREAM, quantity: 1 },
];

const sampleSummary = buildPaymentSummary(sampleLines);

checkNumber('問題6: 合計点数', calcTotalQuantity(sampleLines), 3);
checkNumber('問題6: 税込商品合計', sampleSummary.totalWithTax, 3036);
checkNumber('問題6: 送料', sampleSummary.shippingFee, 0);
checkNumber('問題6: 支払総額', sampleSummary.payableAmount, 3036);
checkNumber(
  '問題6: 無料まであと',
  calcRemainingForFreeShipping(sampleSummary.totalWithTax),
  0
);
checkString(
  '問題6: 明細の小計の並び',
  sampleLines
    .map((line) => formatYen(calcLineTotal(line.product.price, line.quantity)))
    .join(' / '),
  '960円 / 1,800円'
);

// 上限に達している明細だけを注意表示する
function isAtMaxQuantity(line: CartLine): boolean {
  return line.quantity >= MAX_CART_QUANTITY;
}

checkBoolean('問題6: 上限に達した明細', isAtMaxQuantity({ product: SOAP, quantity: 10 }), true);
checkBoolean('問題6: 上限未満の明細', isAtMaxQuantity({ product: SOAP, quantity: 9 }), false);

// ---------------------------------------------------------------------------
// 問題7：ブラウザに保存した内容を復元する
// ---------------------------------------------------------------------------
type StoredCartLine = {
  productId: number;
  quantity: number;
};

function toStoredCart(lines: readonly CartLine[]): StoredCartLine[] {
  return lines.map((line) => ({ productId: line.product.id, quantity: line.quantity }));
}

function isStoredCartLine(value: unknown): value is StoredCartLine {
  return (
    typeof value === 'object' &&
    value !== null &&
    'productId' in value &&
    typeof value.productId === 'number' &&
    'quantity' in value &&
    typeof value.quantity === 'number'
  );
}

function safeJsonParse(raw: string | null): unknown {
  if (raw === null) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function parseStoredCart(raw: string | null, products: readonly ProductSummary[]): CartLine[] {
  const parsed = safeJsonParse(raw);

  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed.filter(isStoredCartLine).flatMap((stored): CartLine[] => {
    const product = products.find((candidate) => candidate.id === stored.productId);

    return product === undefined ? [] : [{ product, quantity: clampQuantity(stored.quantity) }];
  });
}

checkJson('問題7: 保存する形', toStoredCart(step3), [
  { productId: 1, quantity: 2 },
  { productId: 3, quantity: 2 },
]);
checkString(
  '問題7: 保存した文字列から復元できる',
  toLineList(parseStoredCart(JSON.stringify(toStoredCart(step3)), PRODUCTS)),
  '1:2,3:2'
);

const storedCases: { label: string; raw: string | null; expected: string }[] = [
  { label: '保存されていない', raw: null, expected: '' },
  { label: '空の配列', raw: '[]', expected: '' },
  { label: 'JSON として壊れている', raw: '[{"productId":1,', expected: '' },
  { label: '配列ではない', raw: '{"productId":1,"quantity":1}', expected: '' },
  { label: '数量が欠けている', raw: '[{"productId":1}]', expected: '' },
  { label: '数量が文字列', raw: '[{"productId":1,"quantity":"2"}]', expected: '' },
  { label: '知らない商品id', raw: '[{"productId":99,"quantity":1}]', expected: '' },
  { label: '上限を超える数量は丸める', raw: '[{"productId":3,"quantity":99}]', expected: '3:10' },
  {
    label: '壊れた明細だけを捨てる',
    raw: '[{"productId":1},{"productId":2,"quantity":1}]',
    expected: '2:1',
  },
];

for (const { label, raw, expected } of storedCases) {
  checkString(`問題7: ${label}`, toLineList(parseStoredCart(raw, PRODUCTS)), expected);
}

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session22: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session22: ok');
