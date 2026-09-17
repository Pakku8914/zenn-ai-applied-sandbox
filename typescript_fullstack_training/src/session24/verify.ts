// セッション24「フォーム・Server Actions・バリデーション」の検証スクリプト。
//
// この章の画面（フォーム）と Server Action は web フォルダ側にあり、
// src からは web を import できない。そこで検証できるものを次のように分けている。
//
//   - Zod のスキーマ・エラーメッセージの組み立て・状態の作り方・決済スタブの判定
//     → 純粋なロジックなので、web/lib と同じ実装をここに写して検証する
//   - Server Action の配線・useActionState・revalidatePath
//     → verify-all.sh の最後に走る web の型チェックと next build が担保する
//
// 実行: docker compose exec ts npx tsx src/session24/verify.ts

import { readFileSync } from 'node:fs';
import { z } from 'zod';
import { fixturePath } from '../session17/fixtures-path';

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

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ---------------------------------------------------------------------------
// 本文4節：スキーマの定義（web/lib/validation.ts と同じ実装）
// ---------------------------------------------------------------------------
const MAX_CART_QUANTITY = 10;

const productIdSchema = z.coerce
  .number({ error: '商品を選び直してください' })
  .int({ error: '商品を選び直してください' })
  .positive({ error: '商品を選び直してください' });

const quantitySchema = z.coerce
  .number({ error: '数量は数字で入力してください' })
  .int({ error: '数量は整数で入力してください' })
  .min(1, { error: '数量は1点以上にしてください' })
  .max(MAX_CART_QUANTITY, { error: `数量は${MAX_CART_QUANTITY}点以下にしてください` });

const cartItemSchema = z.object({
  productId: productIdSchema,
  quantity: quantitySchema,
});

const productRefSchema = z.object({
  productId: productIdSchema,
});

const customerSchema = z.object({
  name: z
    .string({ error: 'お名前を入力してください' })
    .trim()
    .min(1, { error: 'お名前を入力してください' })
    .max(50, { error: 'お名前は50文字以内で入力してください' }),
  email: z.email({ error: 'メールアドレスの形式が正しくありません' }),
  note: z.string().max(200, { error: '備考は200文字以内で入力してください' }).optional(),
});

type CartItemInput = z.infer<typeof cartItemSchema>;
type ProductRefInput = z.infer<typeof productRefSchema>;
type CustomerInput = z.infer<typeof customerSchema>;

// ---------------------------------------------------------------------------
// 本文4節：失敗を画面に出せる形に変える（web/lib/validation.ts と同じ実装）
// ---------------------------------------------------------------------------
type FieldLabels = Record<string, string>;

const CART_FIELD_LABELS: FieldLabels = {
  productId: '商品',
  quantity: '数量',
};

function toErrorMessages(error: z.ZodError, labels: FieldLabels): string[] {
  return error.issues.map((issue) => {
    const key = issue.path.map((segment) => String(segment)).join('.');
    const label = labels[key];

    return label === undefined ? issue.message : `${label}：${issue.message}`;
  });
}

type CustomerFieldErrors = {
  name: string[];
  email: string[];
  note: string[];
  form: string[];
};

function toCustomerFieldErrors(error: z.ZodError<CustomerInput>): CustomerFieldErrors {
  const flat = z.flattenError(error);

  return {
    name: flat.fieldErrors.name ?? [],
    email: flat.fieldErrors.email ?? [],
    note: flat.fieldErrors.note ?? [],
    form: flat.formErrors,
  };
}

// ---------------------------------------------------------------------------
// 本文5節：z.infer で導出した型が期待どおりであること（代入できれば同じ形）
// ---------------------------------------------------------------------------
const expectedCartItem: { productId: number; quantity: number } = { productId: 3, quantity: 2 };
const _cartItemInput: CartItemInput = expectedCartItem;
const _cartItemBack: { productId: number; quantity: number } = _cartItemInput;
const _productRefInput: ProductRefInput = { productId: 5 };
// 備考は任意なので、無くても代入できる
const _customerInput: CustomerInput = { name: 'デモユーザー', email: 'demo@example.com' };

// 数量を忘れた値は代入できない（型がスキーマから導出されている証拠）
// @ts-expect-error
const _missingQuantity: CartItemInput = { productId: 3 };

checkJson('本文5節: z.infer から作った値', _cartItemBack, { productId: 3, quantity: 2 });
checkString('本文5節: 任意項目は省略できる', _customerInput.note ?? '(なし)', '(なし)');
checkNumber('本文5節: 商品参照の型', _productRefInput.productId, 5);
checkString('本文5節: 型注釈を外した値も同じ形', JSON.stringify(_missingQuantity), '{"productId":3}');

// ---------------------------------------------------------------------------
// 本文4節：数量スキーマが通す入力と弾く入力
// ---------------------------------------------------------------------------
function summarizeQuantity(input: unknown): string {
  const parsed = quantitySchema.safeParse(input);

  return parsed.success
    ? `ok:${parsed.data}`
    : `ng:${parsed.error.issues.map((issue) => issue.message).join(' / ')}`;
}

const quantityCases: { input: unknown; expected: string }[] = [
  { input: '1', expected: 'ok:1' },
  { input: '10', expected: 'ok:10' },
  { input: 3, expected: 'ok:3' },
  { input: '  3  ', expected: 'ok:3' },
  { input: '0', expected: 'ng:数量は1点以上にしてください' },
  { input: '11', expected: 'ng:数量は10点以下にしてください' },
  { input: '1.5', expected: 'ng:数量は整数で入力してください' },
  { input: 'たくさん', expected: 'ng:数量は数字で入力してください' },
  { input: '', expected: 'ng:数量は1点以上にしてください' },
  { input: null, expected: 'ng:数量は1点以上にしてください' },
  { input: '1e2', expected: 'ng:数量は10点以下にしてください' },
  { input: '0x0a', expected: 'ok:10' },
];

for (const { input, expected } of quantityCases) {
  checkString(`本文4節: 数量 ${JSON.stringify(input)}`, summarizeQuantity(input), expected);
}

// ---------------------------------------------------------------------------
// 本文4節：商品 ID スキーマが通す入力と弾く入力
// ---------------------------------------------------------------------------
function summarizeProductId(input: unknown): string {
  const parsed = productIdSchema.safeParse(input);

  return parsed.success
    ? `ok:${parsed.data}`
    : `ng:${parsed.error.issues.map((issue) => issue.message).join(' / ')}`;
}

const productIdCases: { input: unknown; expected: string }[] = [
  { input: '1', expected: 'ok:1' },
  { input: '42', expected: 'ok:42' },
  { input: '-1', expected: 'ng:商品を選び直してください' },
  { input: '0', expected: 'ng:商品を選び直してください' },
  { input: '2.5', expected: 'ng:商品を選び直してください' },
  { input: 'abc', expected: 'ng:商品を選び直してください' },
  { input: null, expected: 'ng:商品を選び直してください' },
];

for (const { input, expected } of productIdCases) {
  checkString(`本文4節: 商品ID ${JSON.stringify(input)}`, summarizeProductId(input), expected);
}

// ---------------------------------------------------------------------------
// 本文4節：フォーム1つ分（2項目）をまとめて検証する
// ---------------------------------------------------------------------------
function summarizeCartItem(values: Record<string, unknown>): string {
  const parsed = cartItemSchema.safeParse(values);

  return parsed.success
    ? `ok:${parsed.data.productId}を${parsed.data.quantity}点`
    : `ng:${toErrorMessages(parsed.error, CART_FIELD_LABELS).join(' / ')}`;
}

checkString(
  '本文4節: 正しいフォーム送信',
  summarizeCartItem({ productId: '3', quantity: '2' }),
  'ok:3を2点'
);
checkString(
  '本文4節: 数量だけが不正',
  summarizeCartItem({ productId: '3', quantity: '99' }),
  'ng:数量：数量は10点以下にしてください'
);
checkString(
  '本文4節: 両方が不正なら2件とも返る',
  summarizeCartItem({ productId: '-3', quantity: 'abc' }),
  'ng:商品：商品を選び直してください / 数量：数量は数字で入力してください'
);
checkString(
  '本文4節: 入力欄が無ければ null が届く',
  summarizeCartItem({ productId: null, quantity: null }),
  'ng:商品：商品を選び直してください / 数量：数量は1点以上にしてください'
);
checkString(
  '本文4節: 余分な項目は無視される（strip）',
  summarizeCartItem({ productId: '3', quantity: '2', price: '1' }),
  'ok:3を2点'
);
checkString(
  '本文4節: 削除フォームは商品IDだけを見る',
  productRefSchema.safeParse({ productId: '4' }).success ? 'ok' : 'ng',
  'ok'
);

// ---------------------------------------------------------------------------
// 練習問題2・3：お届け先スキーマと、項目ごとのエラー
// ---------------------------------------------------------------------------
function summarizeCustomer(values: Record<string, unknown>): CustomerFieldErrors | string {
  const parsed = customerSchema.safeParse(values);

  return parsed.success ? `ok:${parsed.data.name}` : toCustomerFieldErrors(parsed.error);
}

checkJson(
  '練習2: 正しいお届け先',
  summarizeCustomer({ name: ' デモユーザー ', email: 'demo@example.com' }),
  'ok:デモユーザー'
);
checkJson('練習3: 名前が空', summarizeCustomer({ name: '', email: 'demo@example.com' }), {
  name: ['お名前を入力してください'],
  email: [],
  note: [],
  form: [],
});
checkJson('練習3: 名前が空白だけ', summarizeCustomer({ name: '   ', email: 'demo@example.com' }), {
  name: ['お名前を入力してください'],
  email: [],
  note: [],
  form: [],
});
checkJson(
  '練習3: 名前が長すぎる',
  summarizeCustomer({ name: 'あ'.repeat(51), email: 'demo@example.com' }),
  { name: ['お名前は50文字以内で入力してください'], email: [], note: [], form: [] }
);
checkJson('練習3: 名前が入力欄ごと無い', summarizeCustomer({ name: null, email: 'x@y.co' }), {
  name: ['お名前を入力してください'],
  email: [],
  note: [],
  form: [],
});
checkJson('練習3: メールに @ が無い', summarizeCustomer({ name: 'デモ', email: 'demo' }), {
  name: [],
  email: ['メールアドレスの形式が正しくありません'],
  note: [],
  form: [],
});
checkJson(
  '練習3: メールにドメインの末尾が無い',
  summarizeCustomer({ name: 'デモ', email: 'demo@example' }),
  { name: [], email: ['メールアドレスの形式が正しくありません'], note: [], form: [] }
);
checkJson(
  '練習3: 備考が長すぎる',
  summarizeCustomer({ name: 'デモ', email: 'demo@example.com', note: 'あ'.repeat(201) }),
  { name: [], email: [], note: ['備考は200文字以内で入力してください'], form: [] }
);
checkJson(
  '練習3: 2項目とも不正なら両方に入る',
  summarizeCustomer({ name: '', email: 'demo' }),
  {
    name: ['お名前を入力してください'],
    email: ['メールアドレスの形式が正しくありません'],
    note: [],
    form: [],
  }
);
checkString(
  '練習2: 備考が空文字でも通る',
  customerSchema.safeParse({ name: 'デモ', email: 'demo@example.com', note: '' }).success
    ? 'ok'
    : 'ng',
  'ok'
);

// ---------------------------------------------------------------------------
// 本文7節：Server Action が返す状態（判別可能なユニオン。タグは kind）
// ---------------------------------------------------------------------------
type CartActionState =
  | { kind: 'idle' }
  | { kind: 'ok'; message: string }
  | { kind: 'error'; messages: string[] };

function okState(message: string): CartActionState {
  return { kind: 'ok', message };
}

function errorState(messages: readonly string[]): CartActionState {
  return { kind: 'error', messages: [...messages] };
}

function invalidInputState(error: z.ZodError, labels: FieldLabels): CartActionState {
  return errorState(toErrorMessages(error, labels));
}

/** 画面側の分岐と同じ判断を文字列で表す（kind ごとに描くものが違う） */
function describeState(state: CartActionState): string {
  switch (state.kind) {
    case 'idle':
      return '(なにも表示しない)';
    case 'ok':
      return `成功: ${state.message}`;
    case 'error':
      return `失敗: ${state.messages.join(' / ')}`;
    default: {
      const unreachable: never = state;

      throw new Error(`未知の状態です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/** Server Action の中身と同じ流れ（検証 → データベース → 状態）を関数にしたもの */
function runAddToCart(
  values: Record<string, unknown>,
  save: (input: CartItemInput) => { kind: 'ok'; message: string } | { kind: 'error'; message: string }
): CartActionState {
  const parsed = cartItemSchema.safeParse(values);

  if (!parsed.success) {
    return invalidInputState(parsed.error, CART_FIELD_LABELS);
  }

  const change = save(parsed.data);

  return change.kind === 'error' ? errorState([change.message]) : okState(change.message);
}

const alwaysSaved = (input: CartItemInput) => ({
  kind: 'ok' as const,
  message: `商品${input.productId}を${input.quantity}点にしました`,
});
const outOfStock = () => ({ kind: 'error' as const, message: '在庫が足りません（残り3点）' });

checkString('本文7節: 初期状態', describeState({ kind: 'idle' }), '(なにも表示しない)');
checkString(
  '本文7節: 検証を通って保存できた',
  describeState(runAddToCart({ productId: '3', quantity: '2' }, alwaysSaved)),
  '成功: 商品3を2点にしました'
);
checkString(
  '本文7節: 検証で弾かれた（データベースに触らない）',
  describeState(runAddToCart({ productId: '3', quantity: '99' }, alwaysSaved)),
  '失敗: 数量：数量は10点以下にしてください'
);
checkString(
  '本文7節: 検証は通ったが在庫が足りない',
  describeState(runAddToCart({ productId: '3', quantity: '4' }, outOfStock)),
  '失敗: 在庫が足りません（残り3点）'
);

// 検証で弾かれたときは save が1度も呼ばれないことを数で確かめる
let saveCallCount = 0;
const countingSave = (input: CartItemInput) => {
  saveCallCount += 1;

  return { kind: 'ok' as const, message: `商品${input.productId}を${input.quantity}点にしました` };
};

runAddToCart({ productId: '0', quantity: '0' }, countingSave);
checkNumber('本文7節: 不正な入力では保存を呼ばない', saveCallCount, 0);
runAddToCart({ productId: '1', quantity: '1' }, countingSave);
checkNumber('本文7節: 正しい入力では1回だけ保存する', saveCallCount, 1);

// ---------------------------------------------------------------------------
// 練習問題6：URL のクエリを検証する（壊れていても既定値に落とす）
// ---------------------------------------------------------------------------
type SortKey = 'price-asc' | 'price-desc' | 'name-asc';

const SORT_KEYS = ['price-asc', 'price-desc', 'name-asc'] as const;
const DEFAULT_SORT: SortKey = 'price-asc';

const productQuerySchema = z.object({
  category: z.string().trim().min(1).nullable().catch(null),
  sort: z.enum(SORT_KEYS).catch(DEFAULT_SORT),
  page: z.coerce.number().int().min(1).catch(1),
});

type ProductQueryInput = z.infer<typeof productQuerySchema>;

const _defaultQuery: ProductQueryInput = { category: null, sort: DEFAULT_SORT, page: 1 };

checkJson('練習6: 何も指定が無い', productQuerySchema.parse({}), _defaultQuery);
checkJson(
  '練習6: すべて正しい',
  productQuerySchema.parse({ category: 'kitchen', sort: 'price-desc', page: '2' }),
  { category: 'kitchen', sort: 'price-desc', page: 2 }
);
checkJson(
  '練習6: 前後の空白は落とす',
  productQuerySchema.parse({ category: ' kitchen ', sort: 'name-asc', page: '3' }),
  { category: 'kitchen', sort: 'name-asc', page: 3 }
);
checkJson(
  '練習6: 壊れた値は既定値に落ちる',
  productQuerySchema.parse({ category: '   ', sort: 'cheapest', page: '0' }),
  _defaultQuery
);
checkJson('練習6: 負のページ番号', productQuerySchema.parse({ page: '-3' }), _defaultQuery);
checkJson('練習6: 小数のページ番号', productQuerySchema.parse({ page: '1.5' }), _defaultQuery);

// ---------------------------------------------------------------------------
// 本文10節：決済ゲートウェイのスタブと冪等キー（web/lib/payment/gateway.ts と同じ実装）
// ---------------------------------------------------------------------------
type PaymentResult =
  | { kind: 'succeeded'; paymentId: string }
  | { kind: 'failed'; reason: 'card_declined' | 'insufficient_funds' | 'network_error' }
  | { kind: 'pending'; paymentId: string };

type ChargeInput = {
  idempotencyKey: string;
  amount: number;
  orderId: string;
};

function buildIdempotencyKey(orderId: string): string {
  return `charge-${orderId}`;
}

function decidePaymentResult(input: ChargeInput): PaymentResult {
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

class StubPaymentGateway {
  readonly #results = new Map<string, PaymentResult>();
  #chargeCount = 0;

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

function summarizeResult(result: PaymentResult): string {
  return result.kind === 'failed' ? `failed:${result.reason}` : `${result.kind}:${result.paymentId}`;
}

const gateway = new StubPaymentGateway();
const orderKey = buildIdempotencyKey('order-1001');

checkString('本文10節: 冪等キーは注文から決まる', orderKey, 'charge-order-1001');

// 支払総額 1628 円（下2桁が 28）は成功する
const first = await gateway.charge({ idempotencyKey: orderKey, amount: 1628, orderId: 'order-1001' });

checkString('本文10節: 1回目の請求', summarizeResult(first), 'succeeded:pay_charge-order-1001');

// 通信が不安定で読者が送信ボタンを2回押した場合。同じ冪等キーなら課金は1回だけ
const second = await gateway.charge({
  idempotencyKey: orderKey,
  amount: 1628,
  orderId: 'order-1001',
});

checkString('本文10節: 2回目も同じ結果', summarizeResult(second), summarizeResult(first));
checkNumber('本文10節: 課金を試みた回数は1回', gateway.chargeCount, 1);

// 冪等キーを毎回作り直すと、二重決済を止められない
const careless = new StubPaymentGateway();

await careless.charge({ idempotencyKey: 'key-1', amount: 1628, orderId: 'order-1001' });
await careless.charge({ idempotencyKey: 'key-2', amount: 1628, orderId: 'order-1001' });
checkNumber('本文10節: キーが違えば2回課金される', careless.chargeCount, 2);

// 金額の下2桁で失敗系を再現できる
const declined = await new StubPaymentGateway().charge({
  idempotencyKey: 'charge-order-2001',
  amount: 1201,
  orderId: 'order-2001',
});
const pending = await new StubPaymentGateway().charge({
  idempotencyKey: 'charge-order-2002',
  amount: 1202,
  orderId: 'order-2002',
});
const zeroEnding = await new StubPaymentGateway().charge({
  idempotencyKey: 'charge-order-2003',
  amount: 1200,
  orderId: 'order-2003',
});

checkString('本文10節: 下2桁が01なら拒否', summarizeResult(declined), 'failed:card_declined');
checkString(
  '本文10節: 下2桁が02なら保留',
  summarizeResult(pending),
  'pending:pay_charge-order-2002'
);
checkString(
  '本文10節: 下2桁が00なら成功',
  summarizeResult(zeroEnding),
  'succeeded:pay_charge-order-2003'
);

// ---------------------------------------------------------------------------
// 本文4節：壊れたデータを Zod で弾く（Mid03 で手書きした型ガードの置き換え）
// ---------------------------------------------------------------------------
const productSchema = z.object({
  id: z.int().positive(),
  name: z.string().min(1),
  price: z.int().nonnegative(),
  stock: z.int().nonnegative(),
  description: z.string(),
  imageUrl: z.string(),
  categoryId: z.int().positive(),
});

const productsSchema = z.array(productSchema);

/** fixtures の JSON を読み、スキーマに通した結果を短い文字列で表す */
function verifyFixture(fileName: string): string {
  const text = readFileSync(fixturePath(fileName), 'utf-8');
  const raw: unknown = JSON.parse(text);
  const parsed = productsSchema.safeParse(raw);

  if (parsed.success) {
    return `ok:${parsed.data.length}件`;
  }

  const places = parsed.error.issues.map((issue) =>
    issue.path.map((segment) => String(segment)).join('.')
  );

  return `ng:${places.join(',')}`;
}

checkString('本文4節: 正しい fixtures は通る', verifyFixture('products.json'), 'ok:5件');
checkString(
  '本文4節: price が欠けている fixtures は弾かれる',
  verifyFixture('products-missing-field.json'),
  'ng:1.price'
);
checkString(
  '本文4節: price が文字列・stock が負の fixtures は弾かれる',
  verifyFixture('products-wrong-type.json'),
  'ng:0.price,1.stock'
);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session24: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session24: ok');
