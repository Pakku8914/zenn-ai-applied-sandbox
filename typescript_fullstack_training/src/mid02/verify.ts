/**
 * 中間プロジェクト2「型で守るショップドメインモデル」の模範解答を検証する。
 *
 * import / export は「セッション16：モジュール・tsconfig・null 安全」で学ぶため、
 * ドメインの型・関数・クラスと検証コードを1つのファイルにまとめている。
 *
 * このプロジェクトの成果物の核心は「不正な状態が作れないこと」なので、
 * 検証は2段構えになっている。
 *   - 13節: コンパイル時の検証（@ts-expect-error。tsc --noEmit が確認する）
 *   - 15節: 実行時の検証（期待値と一致しなければ非0で終了する）
 *
 * 実行: docker compose exec ts npx tsx src/mid02/verify.ts
 */

// ===== 1. 定数 =====================================================

const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;
/** 1明細あたりの数量の上限（S15 で確定） */
const MAX_CART_QUANTITY = 10;

/** 検証で使う固定の日時（実行するたびに変わらないようにする） */
const PLACED_AT = '2026-08-27T10:00:00.000Z';
const PAID_AT = '2026-08-27T10:05:00.000Z';
const SHIPPED_AT = '2026-08-28T09:00:00.000Z';
const CANCELLED_AT = '2026-08-27T10:10:00.000Z';

// ===== 2. Result 型 ================================================

/** 成功か失敗かを値で表す（S13 で導入した形をそのまま使う） */
type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

// ===== 3. ドメインのエラー =========================================

/** DB の orders.status に保存する値。判別タグではない */
type OrderStatus = 'pending' | 'paid' | 'shipped' | 'cancelled';
type MemberRank = 'gold' | 'silver' | 'bronze' | 'none';
type CancelReason = 'out_of_stock' | 'user_request' | 'payment_failed';

type InvalidQuantity = { kind: 'invalid_quantity'; value: number };
type InvalidMoney = { kind: 'invalid_money'; value: number };
type StockShortage = {
  kind: 'stock_shortage';
  productId: number;
  productName: string;
  requested: number;
  available: number;
};
type EmptyCart = { kind: 'empty_cart' };
type ProductNotFound = { kind: 'product_not_found'; productId: number };
type InvalidTransition = { kind: 'invalid_transition'; from: OrderStatus; to: OrderStatus };
type InvalidProductInput = {
  kind: 'invalid_product_input';
  field: keyof ProductInput;
  reason: string;
};

/** ドメインで起こりうる失敗の全部。判別タグは本書共通の kind */
type DomainError =
  | InvalidQuantity
  | InvalidMoney
  | StockShortage
  | EmptyCart
  | ProductNotFound
  | InvalidTransition
  | InvalidProductInput;

/**
 * 到達しないはずの分岐で呼ぶ。引数の型が never でなくなった時点でコンパイルエラーになる。
 * 例外そのものの扱いは「セッション18：エラーハンドリングと型安全な失敗表現」で学ぶ。
 */
function assertNever(value: never): never {
  throw new Error(`未対応のケースがあります: ${JSON.stringify(value)}`);
}

const CANCEL_REASON_LABEL: Record<CancelReason, string> = {
  out_of_stock: '在庫不足',
  user_request: 'お客様のご依頼',
  payment_failed: '決済の失敗',
};

/** 失敗を利用者向けの1文にする。case を1つ忘れると default でコンパイルエラーになる */
function describeError(error: DomainError): string {
  switch (error.kind) {
    case 'invalid_quantity':
      return `数量は1以上${MAX_CART_QUANTITY}以下の整数で指定してください（受け取った値: ${error.value}）`;
    case 'invalid_money':
      return `金額は0以上の整数（円）で指定してください（受け取った値: ${error.value}）`;
    case 'stock_shortage':
      return `${error.productName}の在庫が足りません（希望 ${error.requested}点 / 在庫 ${error.available}点）`;
    case 'empty_cart':
      return 'カートが空です。商品を追加してください';
    case 'product_not_found':
      return `商品が見つかりません（productId: ${error.productId}）`;
    case 'invalid_transition':
      return `${error.from} の注文を ${error.to} にはできません`;
    case 'invalid_product_input':
      return `${error.field} が不正です: ${error.reason}`;
    default:
      return assertNever(error);
  }
}

// ===== 4. 値オブジェクト（Money / Quantity）========================

/**
 * 金額（円・整数・0以上）。
 * # のフィールドを持つので、同じ形のオブジェクトを Money として使うことはできない。
 */
class Money {
  readonly #amount: number;

  private constructor(amount: number) {
    this.#amount = amount;
  }

  get amount(): number {
    return this.#amount;
  }

  /** 0円はいつでも作れる（合計の初期値に使う） */
  static zero(): Money {
    return new Money(0);
  }

  /** 唯一の入口。ここを通らない金額は存在しない */
  static create(amount: number): Result<Money, InvalidMoney> {
    if (!Number.isInteger(amount) || amount < 0) {
      return { kind: 'error', error: { kind: 'invalid_money', value: amount } };
    }
    return { kind: 'ok', value: new Money(amount) };
  }

  /** 0以上の整数どうしの足し算は0以上の整数。だから失敗しない */
  add(other: Money): Money {
    return new Money(this.#amount + other.#amount);
  }

  /** 掛ける相手が Quantity（1以上10以下の整数）なので、こちらも失敗しない */
  times(quantity: Quantity): Money {
    return new Money(this.#amount * quantity.value);
  }
}

/** 1明細の数量（1以上 MAX_CART_QUANTITY 以下の整数） */
class Quantity {
  readonly #value: number;

  private constructor(value: number) {
    this.#value = value;
  }

  get value(): number {
    return this.#value;
  }

  static create(value: number): Result<Quantity, InvalidQuantity> {
    if (!Number.isInteger(value) || value < 1 || value > MAX_CART_QUANTITY) {
      return { kind: 'error', error: { kind: 'invalid_quantity', value } };
    }
    return { kind: 'ok', value: new Quantity(value) };
  }

  /** 合算は上限を超えうるので、こちらは Result を返す */
  plus(other: Quantity): Result<Quantity, InvalidQuantity> {
    return Quantity.create(this.#value + other.#value);
  }
}

// ===== 5. 商品（生のレコードとカタログ商品）========================

/** DB や JSON から来る生のレコード。price はただの number なので信用できない */
type Product = {
  readonly id: number;
  readonly name: string;
  readonly price: number;
  readonly stock: number;
  readonly description: string;
  readonly imageUrl: string;
  readonly categoryId: number;
};

/** 検証を通した商品。price が Money なので、負の金額の商品は存在しない */
type CatalogProduct = Omit<Product, 'price'> & { readonly price: Money };

/** 商品マスタ（requirements.md の表・fixtures と同じ値） */
const RAW_PRODUCTS: readonly Product[] = [
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

/** 生のレコードをカタログ商品にする（境界で1回だけ検証する） */
function toCatalogProduct(product: Product): Result<CatalogProduct, DomainError> {
  const price = Money.create(product.price);
  if (price.kind === 'error') {
    return price;
  }
  return { kind: 'ok', value: { ...product, price: price.value } };
}

/** 検証を通った商品だけをカタログに入れる */
function buildCatalog(products: readonly Product[]): Map<number, CatalogProduct> {
  const catalog = new Map<number, CatalogProduct>();
  for (const product of products) {
    const converted = toCatalogProduct(product);
    if (converted.kind === 'ok') {
      catalog.set(product.id, converted.value);
    }
  }
  return catalog;
}

const CATALOG = buildCatalog(RAW_PRODUCTS);

function findProduct(
  catalog: Map<number, CatalogProduct>,
  productId: number
): Result<CatalogProduct, ProductNotFound> {
  const product = catalog.get(productId);
  if (product === undefined) {
    return { kind: 'error', error: { kind: 'product_not_found', productId } };
  }
  return { kind: 'ok', value: product };
}

// ===== 6. ユーティリティ型で導いた入力の型 =========================

/** 商品登録フォームの入力。id は保存時に採番するので持たない */
type ProductInput = Omit<Product, 'id'>;
/** 部分更新の入力。触るフィールドだけを送る */
type ProductPatch = Partial<ProductInput>;
/** 一覧表示に必要な分だけ */
type ProductListItem = Readonly<Pick<Product, 'id' | 'name' | 'imageUrl'>>;

/** 入力エラーを組み立てる小さなヘルパー（同じ形を3回書かないため） */
function invalidInput(
  field: keyof ProductInput,
  reason: string
): Result<ProductInput, InvalidProductInput> {
  return { kind: 'error', error: { kind: 'invalid_product_input', field, reason } };
}

function validateProductInput(input: ProductInput): Result<ProductInput, InvalidProductInput> {
  if (input.name.trim().length === 0) {
    return invalidInput('name', '商品名を入力してください');
  }
  if (!Number.isInteger(input.price) || input.price < 1) {
    return invalidInput('price', '1以上の整数（円）で入力してください');
  }
  if (!Number.isInteger(input.stock) || input.stock < 0) {
    return invalidInput('stock', '0以上の整数で入力してください');
  }
  return { kind: 'ok', value: input };
}

/** 入力 + 採番した id からカタログ商品を作る */
function registerProduct(nextId: number, input: ProductInput): Result<CatalogProduct, DomainError> {
  const validated = validateProductInput(input);
  if (validated.kind === 'error') {
    return validated;
  }
  const price = Money.create(validated.value.price);
  if (price.kind === 'error') {
    return price;
  }
  return { kind: 'ok', value: { ...validated.value, id: nextId, price: price.value } };
}

/** 部分更新。元のレコードは書き換えず、新しいレコードを返す */
function applyPatch(product: Product, patch: ProductPatch): Product {
  return { ...product, ...patch };
}

function toListItem(product: Product): ProductListItem {
  return { id: product.id, name: product.name, imageUrl: product.imageUrl };
}

// ===== 7. カート ===================================================

type CartLine = { readonly product: CatalogProduct; readonly quantity: Quantity };

/**
 * カート。数量は Quantity でしか受け取らないので、
 * 「0点」「11点」「1.5点」の明細は最初から作れない。
 */
class Cart {
  readonly #lines: readonly CartLine[];

  private constructor(
    readonly userId: number,
    lines: readonly CartLine[]
  ) {
    this.#lines = lines;
  }

  static empty(userId: number): Cart {
    return new Cart(userId, []);
  }

  /** S15 と同じく、外に配るのはコピー（型でも readonly を宣言する） */
  get lines(): readonly CartLine[] {
    return [...this.#lines];
  }

  get lineCount(): number {
    return this.#lines.length;
  }

  get itemCount(): number {
    return this.#lines.reduce((total, line) => total + line.quantity.value, 0);
  }

  get isEmpty(): boolean {
    return this.#lines.length === 0;
  }

  /** 小計（税抜）。Money の足し算だけで作れるので失敗しない */
  get subtotal(): Money {
    return this.#lines.reduce(
      (total, line) => total.add(line.product.price.times(line.quantity)),
      Money.zero()
    );
  }

  /** 同じ商品は1明細にまとめる。合算で上限を超えたときだけ失敗する */
  add(product: CatalogProduct, quantity: Quantity): Result<Cart, DomainError> {
    const existing = this.#lines.find((line) => line.product.id === product.id);
    if (existing === undefined) {
      return { kind: 'ok', value: new Cart(this.userId, [...this.#lines, { product, quantity }]) };
    }
    const merged = existing.quantity.plus(quantity);
    if (merged.kind === 'error') {
      return merged;
    }
    const mergedQuantity = merged.value;
    const nextLines = this.#lines.map((line) =>
      line.product.id === product.id ? { product, quantity: mergedQuantity } : line
    );
    return { kind: 'ok', value: new Cart(this.userId, nextLines) };
  }

  /** 明細を注文明細に写す。数量と単価は検証済みの値をそのまま渡す */
  toOrderItems(orderId: string): readonly OrderItem[] {
    return this.#lines.map((line, index) => ({
      id: index + 1,
      orderId,
      productId: line.product.id,
      quantity: line.quantity,
      unitPrice: line.product.price,
    }));
  }
}

// ===== 8. 注文（判別可能なユニオン）===============================

type OrderItem = {
  readonly id: number;
  readonly orderId: string;
  readonly productId: number;
  readonly quantity: Quantity;
  readonly unitPrice: Money;
};

/** どの状態でも必ず持つフィールド */
type OrderBase = {
  readonly id: string;
  readonly userId: number;
  readonly items: readonly OrderItem[];
  readonly totalAmount: Money;
  readonly createdAt: string;
};

type PendingOrder = OrderBase & { readonly kind: 'pending' };
type PaidOrder = OrderBase & {
  readonly kind: 'paid';
  readonly paidAt: string;
  readonly paymentId: string;
};
type ShippedOrder = OrderBase & {
  readonly kind: 'shipped';
  readonly paidAt: string;
  readonly paymentId: string;
  readonly shippedAt: string;
  readonly trackingNumber: string;
};
type CancelledOrder = OrderBase & {
  readonly kind: 'cancelled';
  readonly cancelledAt: string;
  readonly cancelReason: CancelReason;
};

type Order = PendingOrder | PaidOrder | ShippedOrder | CancelledOrder;
/** キャンセルできる状態にだけ名前を付ける */
type CancellableOrder = PendingOrder | PaidOrder;

/** 判別タグ kind から、DB に保存する status を求める */
const STATUS_BY_KIND: Record<Order['kind'], OrderStatus> = {
  pending: 'pending',
  paid: 'paid',
  shipped: 'shipped',
  cancelled: 'cancelled',
};

/**
 * kind と status の集合がずれたら、この行がコンパイルエラーになる。
 * どちらか片方にだけ状態を足す事故を型で防ぐための1行。
 */
const statusMatchesKind: Record<OrderStatus, Order['kind']> = STATUS_BY_KIND;

function orderStatusOf(order: Order): OrderStatus {
  return STATUS_BY_KIND[order.kind];
}

/** 状態ごとに表示できる情報が違う。絞り込んだ中だけで固有フィールドを読む */
function describeOrder(order: Order): string {
  switch (order.kind) {
    case 'pending':
      return `${order.id}: お支払い待ち（${order.totalAmount.amount}円）`;
    case 'paid':
      return `${order.id}: お支払い済み（${order.totalAmount.amount}円 / 支払 ${order.paidAt}）`;
    case 'shipped':
      return `${order.id}: 発送済み（追跡番号 ${order.trackingNumber} / 発送 ${order.shippedAt}）`;
    case 'cancelled':
      return `${order.id}: キャンセル（理由: ${CANCEL_REASON_LABEL[order.cancelReason]}）`;
    default:
      return assertNever(order);
  }
}

// ===== 9. 金額の計算 ===============================================

type DiscountRule = (subtotal: number) => number;

type PaymentSummary = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

/** S05 の (price: number, quantity: number) を、本章で Money と Quantity に変えた */
function calcLineTotal(unitPrice: Money, quantity: Quantity): Money {
  return unitPrice.times(quantity);
}

function calcSubtotal(items: readonly OrderItem[]): Money {
  return items.reduce(
    (total, item) => total.add(calcLineTotal(item.unitPrice, item.quantity)),
    Money.zero()
  );
}

/** 送料。判定基準は税込商品合計 */
function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

const DISCOUNT_PERCENT_BY_RANK: Record<MemberRank, number> = {
  gold: 10,
  silver: 5,
  bronze: 3,
  none: 0,
};

function resolveDiscountRule(rank: MemberRank): DiscountRule {
  const percent = DISCOUNT_PERCENT_BY_RANK[rank];
  return (subtotal) => Math.floor((subtotal * percent) / 100);
}

/** 本書共通の計算手順1〜7。途中は number のまま扱う */
function buildPaymentSummary(items: readonly OrderItem[], rule: DiscountRule): PaymentSummary {
  const subtotal = calcSubtotal(items).amount; // 手順1
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  const shippingFee = calcShippingFee(totalWithTax); // 手順6
  return {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount: totalWithTax + shippingFee, // 手順7
  };
}

// ===== 10. 在庫引当と注文の確定 ====================================

type StockReservation = {
  readonly productId: number;
  readonly reserved: number;
  readonly remainingStock: number;
};

type CheckoutInput = {
  readonly orderId: string;
  readonly rank: MemberRank;
  readonly now: string;
};

type CheckoutResult = {
  readonly order: PendingOrder;
  readonly summary: PaymentSummary;
  readonly reservations: readonly StockReservation[];
};

/** 在庫引当。失敗する理由は在庫不足だけなので、エラー型も1つに絞れる */
function reserveStock(
  catalog: Map<number, CatalogProduct>,
  lines: readonly CartLine[]
): Result<readonly StockReservation[], StockShortage> {
  const reservations: StockReservation[] = [];
  for (const line of lines) {
    const requested = line.quantity.value;
    const current = catalog.get(line.product.id);
    const available = current === undefined ? 0 : current.stock;
    if (available < requested) {
      return {
        kind: 'error',
        error: {
          kind: 'stock_shortage',
          productId: line.product.id,
          productName: line.product.name,
          requested,
          available,
        },
      };
    }
    reservations.push({
      productId: line.product.id,
      reserved: requested,
      remainingStock: available - requested,
    });
  }
  return { kind: 'ok', value: reservations };
}

/** 注文の確定。返すのは Order ではなく PendingOrder（次に呼べる関数が型で決まる） */
function checkout(
  cart: Cart,
  catalog: Map<number, CatalogProduct>,
  input: CheckoutInput
): Result<CheckoutResult, DomainError> {
  if (cart.isEmpty) {
    return { kind: 'error', error: { kind: 'empty_cart' } };
  }
  const reserved = reserveStock(catalog, cart.lines);
  if (reserved.kind === 'error') {
    return reserved; // 狭いエラー型は広いエラー型にそのまま返せる
  }
  const items = cart.toOrderItems(input.orderId);
  const summary = buildPaymentSummary(items, resolveDiscountRule(input.rank));
  const totalAmount = Money.create(summary.payableAmount);
  if (totalAmount.kind === 'error') {
    return totalAmount;
  }
  const order: PendingOrder = {
    kind: 'pending',
    id: input.orderId,
    userId: cart.userId,
    items,
    totalAmount: totalAmount.value,
    createdAt: input.now,
  };
  return { kind: 'ok', value: { order, summary, reservations: reserved.value } };
}

// ===== 11. 状態遷移 ================================================

/** 支払い。引数が PendingOrder なので、支払い済みの注文は渡せない */
function payOrder(order: PendingOrder, paidAt: string, paymentId: string): PaidOrder {
  return { ...order, kind: 'paid', paidAt, paymentId };
}

/** 発送。引数が PaidOrder なので、未払い・キャンセル済みの注文は渡せない */
function shipOrder(order: PaidOrder, shippedAt: string, trackingNumber: string): ShippedOrder {
  return { ...order, kind: 'shipped', shippedAt, trackingNumber };
}

/**
 * キャンセル。引数は pending か paid だけ。
 * 決済情報（paidAt / paymentId）はここで意図的に落としている。
 */
function cancelOrder(
  order: CancellableOrder,
  cancelledAt: string,
  cancelReason: CancelReason
): CancelledOrder {
  return {
    kind: 'cancelled',
    id: order.id,
    userId: order.userId,
    items: order.items,
    totalAmount: order.totalAmount,
    createdAt: order.createdAt,
    cancelledAt,
    cancelReason,
  };
}

/** DB から読んだ Order（状態が実行時にしか分からない）を絞り込んでからキャンセルする */
function requestCancel(
  order: Order,
  cancelledAt: string,
  cancelReason: CancelReason
): Result<CancelledOrder, InvalidTransition> {
  if (order.kind === 'shipped' || order.kind === 'cancelled') {
    return {
      kind: 'error',
      error: { kind: 'invalid_transition', from: orderStatusOf(order), to: 'cancelled' },
    };
  }
  return { kind: 'ok', value: cancelOrder(order, cancelledAt, cancelReason) };
}

// ===== 12. 集計 ====================================================

type OrderSummary = {
  readonly totalCount: number;
  readonly countByStatus: Record<OrderStatus, number>;
  readonly salesAmount: Money;
  readonly pendingAmount: Money;
};

/** 売上は paid と shipped の合計。pending と cancelled は売上に数えない */
function summarizeOrders(orders: readonly Order[]): OrderSummary {
  const countByStatus: Record<OrderStatus, number> = {
    pending: 0,
    paid: 0,
    shipped: 0,
    cancelled: 0,
  };
  let salesAmount = Money.zero();
  let pendingAmount = Money.zero();

  for (const order of orders) {
    countByStatus[orderStatusOf(order)] += 1;
    if (order.kind === 'paid' || order.kind === 'shipped') {
      salesAmount = salesAmount.add(order.totalAmount);
    }
    if (order.kind === 'pending') {
      pendingAmount = pendingAmount.add(order.totalAmount);
    }
  }

  return { totalCount: orders.length, countByStatus, salesAmount, pendingAmount };
}

function describeOrderSummary(summary: OrderSummary): string {
  return [
    `件数 ${summary.totalCount}`,
    `pending ${summary.countByStatus.pending}`,
    `paid ${summary.countByStatus.paid}`,
    `shipped ${summary.countByStatus.shipped}`,
    `cancelled ${summary.countByStatus.cancelled}`,
    `売上 ${summary.salesAmount.amount}円`,
    `未払い ${summary.pendingAmount.amount}円`,
  ].join(' / ');
}

function describeReservations(reservations: readonly StockReservation[]): string {
  return reservations
    .map((reservation) => `${reservation.productId}:${reservation.reserved}点→残${reservation.remainingStock}`)
    .join(' / ');
}

// ===== 13. 「書けないコード」の証明（コンパイル時の検証）===========
// この節の関数は一度も呼ばない。目的は実行することではなく、
// 「この書き方はコンパイルエラーになる」ことを tsc --noEmit に確認させること。
// このディレクティブは「次の1行がエラーであること」を要求するので、型定義を
// ゆるめてエラーが出なくなった瞬間に、その行で型チェックが失敗する。
// （説明文の行頭にディレクティブ名を書くと、tsc がそれを本物の指示として
//  解釈してしまうため、この節では名前を行頭に置いていない。）

function proveOrderStateIsGuarded(
  pending: PendingOrder,
  paid: PaidOrder,
  shipped: ShippedOrder,
  cancelled: CancelledOrder,
  anyOrder: Order
): void {
  // @ts-expect-error paidAt を持つのは paid と shipped の注文だけ
  const paidAtOfPending: string = pending.paidAt;
  // @ts-expect-error Order のままでは読めない。まず kind で絞り込む
  const paidAtOfUnion: string = anyOrder.paidAt;
  // @ts-expect-error 支払い済みの注文をもう一度支払うことはできない
  payOrder(paid, PAID_AT, 'pay_9999');
  // @ts-expect-error 発送済みの注文はキャンセルできない
  cancelOrder(shipped, CANCELLED_AT, 'user_request');
  // @ts-expect-error キャンセル済みの注文は発送できない
  shipOrder(cancelled, SHIPPED_AT, 'TRK-9999');
  // @ts-expect-error 確定した注文の合計金額は書き換えられない
  pending.totalAmount = Money.zero();
  // @ts-expect-error readonly の配列なので、あとから明細を抜き差しできない
  pending.items.pop();
}

function proveValueObjectsAreGuarded(cart: Cart, product: CatalogProduct): void {
  // @ts-expect-error 数量に生の数値は渡せない（Quantity.create を通す）
  cart.add(product, 3);
  // @ts-expect-error #value を持たないオブジェクトは Quantity にならない
  const fakeQuantity: Quantity = { value: 999 };
  // @ts-expect-error コンストラクタが private なので new できない
  const forcedQuantity = new Quantity(999);
  // @ts-expect-error 金額に生の数値を入れられない
  const rawPrice: Money = 480;
  // @ts-expect-error 金額の中身は読み取り専用（ゲッターしかない）
  product.price.amount = 100;
}

function proveProductInputIsDerived(input: ProductInput): void {
  // @ts-expect-error ProductInput に id は無いので、そのまま Product にはできない
  const product: Product = input;
}

/** cancelled の分岐を忘れた版。default に来る値が never にならないので落ちる */
function describeOrderMissingCase(order: Order): string {
  switch (order.kind) {
    case 'pending':
      return 'お支払い待ち';
    case 'paid':
      return 'お支払い済み';
    case 'shipped':
      return '発送済み';
    default:
      // @ts-expect-error cancelled を処理していないので order は CancelledOrder のまま残っている
      return assertNever(order);
  }
}

// ===== 14. 検証ヘルパー ============================================

let failedCount = 0;

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label}`);
    console.error(`    期待値: ${expected}`);
    console.error(`    実際　: ${actual}`);
    failedCount += 1;
  }
}

function checkNumber(label: string, actual: number, expected: number): void {
  checkString(label, `${actual}`, `${expected}`);
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  checkString(label, `${actual}`, `${expected}`);
}

/** 成功するはずの Result から値を取り出す（検証コード専用） */
function expectOk<T>(label: string, result: Result<T, DomainError>): T {
  if (result.kind === 'error') {
    throw new Error(`${label}: ${describeError(result.error)}`);
  }
  return result.value;
}

/** 失敗するはずの Result のメッセージを取り出す（成功したら検証失敗） */
function errorMessageOf<T>(label: string, result: Result<T, DomainError>): string {
  if (result.kind === 'ok') {
    failedCount += 1;
    console.error(`NG: ${label} — 失敗するはずが成功しました`);
    return '';
  }
  return describeError(result.error);
}

function requireRawProduct(productId: number): Product {
  const found = RAW_PRODUCTS.find((product) => product.id === productId);
  if (found === undefined) {
    throw new Error(`商品マスタに見つかりません: ${productId}`);
  }
  return found;
}

// ===== 15. 実行時の検証 ============================================

// --- 課題1: 値オブジェクト -----------------------------------------
const quantity1 = expectOk('数量1', Quantity.create(1));
const quantity2 = expectOk('数量2', Quantity.create(2));
const quantity3 = expectOk('数量3', Quantity.create(3));
const quantity4 = expectOk('数量4', Quantity.create(4));
const quantity8 = expectOk('数量8', Quantity.create(8));

checkNumber('課題1: 上限ぴったりは作れる', expectOk('数量10', Quantity.create(10)).value, 10);
checkString(
  '課題1: 0点は作れない',
  errorMessageOf('数量0', Quantity.create(0)),
  '数量は1以上10以下の整数で指定してください（受け取った値: 0）'
);
checkString(
  '課題1: 11点は作れない',
  errorMessageOf('数量11', Quantity.create(11)),
  '数量は1以上10以下の整数で指定してください（受け取った値: 11）'
);
checkString(
  '課題1: 小数は作れない',
  errorMessageOf('数量1.5', Quantity.create(1.5)),
  '数量は1以上10以下の整数で指定してください（受け取った値: 1.5）'
);
checkString(
  '課題1: 合算で上限を超えると失敗する',
  errorMessageOf('3点 + 8点', quantity3.plus(quantity8)),
  '数量は1以上10以下の整数で指定してください（受け取った値: 11）'
);
checkNumber('課題1: 合算が上限内なら成功する', expectOk('2点 + 8点', quantity2.plus(quantity8)).value, 10);

checkNumber('課題1: 0円は作れる', Money.zero().amount, 0);
checkString(
  '課題1: 負の金額は作れない',
  errorMessageOf('金額-100', Money.create(-100)),
  '金額は0以上の整数（円）で指定してください（受け取った値: -100）'
);
checkString(
  '課題1: 小数の金額は作れない',
  errorMessageOf('金額1.5', Money.create(1.5)),
  '金額は0以上の整数（円）で指定してください（受け取った値: 1.5）'
);
const money480 = expectOk('金額480', Money.create(480));
checkNumber('課題1: 足し算', money480.add(money480).amount, 960);
checkNumber('課題1: 数量倍（480円 × 3点）', money480.times(quantity3).amount, 1440);

// --- 課題2: 商品とカタログ -----------------------------------------
checkNumber('課題2: カタログの件数', CATALOG.size, 5);
const soap = expectOk('石けん', findProduct(CATALOG, 1));
const mug = expectOk('マグカップ', findProduct(CATALOG, 3));
const cloth = expectOk('ふきん', findProduct(CATALOG, 4));
checkNumber('課題2: 石けんの単価', soap.price.amount, 480);
checkNumber('課題2: マグカップの在庫', mug.stock, 3);
checkNumber('課題2: ふきんの在庫は0のまま', cloth.stock, 0);
checkString('課題2: 石けんの画像パス', soap.imageUrl, '/images/products/lavender-soap.png');
checkString(
  '課題2: 見つからない商品',
  errorMessageOf('商品99', findProduct(CATALOG, 99)),
  '商品が見つかりません（productId: 99）'
);
checkString(
  '課題2: 負の金額の商品はカタログ商品にできない',
  errorMessageOf('負の金額の商品', toCatalogProduct({ ...requireRawProduct(1), price: -480 })),
  '金額は0以上の整数（円）で指定してください（受け取った値: -480）'
);
checkNumber(
  '課題2: 不正な商品はカタログに入らない',
  buildCatalog([requireRawProduct(1), { ...requireRawProduct(2), price: -1 }]).size,
  1
);

// --- 課題3: 注文の状態を型で表す（実行時に確認できる部分）---------
checkString('課題3: kind から status を求める', STATUS_BY_KIND.paid, 'paid');
checkString('課題3: 型の対応表も同じ値', statusMatchesKind.shipped, 'shipped');

// --- 課題4: Result で失敗を返す（カートと在庫引当）-----------------
const emptyCart = Cart.empty(1);
const cartWithSoap = expectOk('石けん3点', emptyCart.add(soap, quantity3));
const cart = expectOk('マグカップ1点', cartWithSoap.add(mug, quantity1));

checkBoolean('課題4: 空のカート', emptyCart.isEmpty, true);
checkNumber('課題4: 明細数', cart.lineCount, 2);
checkNumber('課題4: 点数', cart.itemCount, 4);
checkNumber('課題4: 小計', cart.subtotal.amount, 3790);
checkNumber('課題4: 元のカートは変わらない', emptyCart.lineCount, 0);
checkNumber('課題4: 追加前のカートも変わらない', cartWithSoap.itemCount, 3);

const cartMerged = expectOk('石けんをもう2点', cart.add(soap, quantity2));
checkNumber('課題4: 同じ商品は1明細にまとまる', cartMerged.lineCount, 2);
checkNumber('課題4: 数量は合算される', cartMerged.itemCount, 6);
checkString(
  '課題4: 合算で上限を超えると失敗する',
  errorMessageOf('石けん3点 + 8点', cart.add(soap, quantity8)),
  '数量は1以上10以下の整数で指定してください（受け取った値: 11）'
);
checkBoolean('課題4: 外に配る明細はコピー', cart.lines !== cart.lines, true);

const reservations = expectOk('在庫引当', reserveStock(CATALOG, cart.lines));
checkString('課題4: 引当の結果', describeReservations(reservations), '1:3点→残21 / 3:1点→残2');

const cartMug4 = expectOk('マグカップ4点', Cart.empty(1).add(mug, quantity4));
checkString(
  '課題4: 在庫を超える引当は失敗する',
  errorMessageOf('マグカップ4点', reserveStock(CATALOG, cartMug4.lines)),
  'マグカップの在庫が足りません（希望 4点 / 在庫 3点）'
);
const cartCloth = expectOk('ふきん1点', Cart.empty(1).add(cloth, quantity1));
checkString(
  '課題4: 在庫0の商品は引当できない',
  errorMessageOf('ふきん1点', reserveStock(CATALOG, cartCloth.lines)),
  'リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）'
);

// --- 課題5: ユーティリティ型で導いた入力の型 -----------------------
const bathSaltInput: ProductInput = {
  name: '入浴剤',
  price: 650,
  stock: 10,
  description: 'ゆずの香りの入浴剤です。',
  imageUrl: '/images/products/no-image.png',
  categoryId: 1,
};

const registered = expectOk('入浴剤の登録', registerProduct(6, bathSaltInput));
checkNumber('課題5: 採番された id', registered.id, 6);
checkNumber('課題5: 登録した単価', registered.price.amount, 650);
checkString(
  '課題5: 空の商品名は拒否する',
  errorMessageOf('空の商品名', registerProduct(7, { ...bathSaltInput, name: '   ' })),
  'name が不正です: 商品名を入力してください'
);
checkString(
  '課題5: 単価0は拒否する',
  errorMessageOf('単価0', registerProduct(7, { ...bathSaltInput, price: 0 })),
  'price が不正です: 1以上の整数（円）で入力してください'
);
checkString(
  '課題5: 小数の単価は拒否する',
  errorMessageOf('単価1200.5', registerProduct(7, { ...bathSaltInput, price: 1200.5 })),
  'price が不正です: 1以上の整数（円）で入力してください'
);
checkString(
  '課題5: 負の在庫は拒否する',
  errorMessageOf('在庫-1', registerProduct(7, { ...bathSaltInput, stock: -1 })),
  'stock が不正です: 0以上の整数で入力してください'
);
checkNumber(
  '課題5: 在庫0は受け付ける',
  expectOk('在庫0', registerProduct(7, { ...bathSaltInput, stock: 0 })).stock,
  0
);

const rawSoap = requireRawProduct(1);
const patched = applyPatch(rawSoap, { price: 500, stock: 30 });
checkNumber('課題5: 部分更新で単価が変わる', patched.price, 500);
checkNumber('課題5: 部分更新で在庫が変わる', patched.stock, 30);
checkString('課題5: 触っていない項目は元のまま', patched.name, 'ラベンダーの石けん');
checkNumber('課題5: 元のレコードは変わらない', rawSoap.price, 480);
checkString(
  '課題5: 一覧用に絞った形',
  JSON.stringify(toListItem(rawSoap)),
  '{"id":1,"name":"ラベンダーの石けん","imageUrl":"/images/products/lavender-soap.png"}'
);

// --- 課題6: 状態遷移と網羅性チェック -------------------------------
const checkoutNone = expectOk(
  'ORD-1001 の確定',
  checkout(cart, CATALOG, { orderId: 'ORD-1001', rank: 'none', now: PLACED_AT })
);
const checkoutGold = expectOk(
  'ORD-1002 の確定',
  checkout(cart, CATALOG, { orderId: 'ORD-1002', rank: 'gold', now: PLACED_AT })
);
const cartSoapOnly = expectOk('石けん2点', Cart.empty(1).add(soap, quantity2));
const checkoutSmall = expectOk(
  'ORD-1003 の確定',
  checkout(cartSoapOnly, CATALOG, { orderId: 'ORD-1003', rank: 'none', now: PLACED_AT })
);
const checkoutForCancel = expectOk(
  'ORD-1004 の確定',
  checkout(cart, CATALOG, { orderId: 'ORD-1004', rank: 'none', now: PLACED_AT })
);

const pendingOrder = checkoutNone.order;
const paidOrder = payOrder(pendingOrder, PAID_AT, 'pay_0001');
const paidGoldOrder = payOrder(checkoutGold.order, PAID_AT, 'pay_0002');
const shippedOrder = shipOrder(
  payOrder(checkoutSmall.order, PAID_AT, 'pay_0003'),
  SHIPPED_AT,
  'TRK-0001'
);
const cancelledOrder = cancelOrder(checkoutForCancel.order, CANCELLED_AT, 'out_of_stock');

checkString('課題6: pending の表示', describeOrder(pendingOrder), 'ORD-1001: お支払い待ち（4169円）');
checkString(
  '課題6: paid の表示',
  describeOrder(paidOrder),
  'ORD-1001: お支払い済み（4169円 / 支払 2026-08-27T10:05:00.000Z）'
);
checkString(
  '課題6: shipped の表示',
  describeOrder(shippedOrder),
  'ORD-1003: 発送済み（追跡番号 TRK-0001 / 発送 2026-08-28T09:00:00.000Z）'
);
checkString(
  '課題6: cancelled の表示',
  describeOrder(cancelledOrder),
  'ORD-1004: キャンセル（理由: 在庫不足）'
);
checkString('課題6: 支払い後の status', orderStatusOf(paidOrder), 'paid');
checkString('課題6: 発送後の status', orderStatusOf(shippedOrder), 'shipped');
checkNumber('課題6: 支払っても金額は変わらない', paidOrder.totalAmount.amount, 4169);
checkString('課題6: 支払っても作成日時は変わらない', paidOrder.createdAt, PLACED_AT);
checkString('課題6: 発送済みも支払情報を持つ', shippedOrder.paymentId, 'pay_0003');
checkNumber('課題6: 明細は引き継がれる', shippedOrder.items.length, 1);

checkString(
  '課題6: pending はキャンセルできる',
  describeOrder(expectOk('pending のキャンセル', requestCancel(pendingOrder, CANCELLED_AT, 'user_request'))),
  'ORD-1001: キャンセル（理由: お客様のご依頼）'
);
checkString(
  '課題6: paid もキャンセルできる',
  orderStatusOf(expectOk('paid のキャンセル', requestCancel(paidOrder, CANCELLED_AT, 'user_request'))),
  'cancelled'
);
checkString(
  '課題6: shipped はキャンセルできない',
  errorMessageOf('shipped のキャンセル', requestCancel(shippedOrder, CANCELLED_AT, 'user_request')),
  'shipped の注文を cancelled にはできません'
);
checkString(
  '課題6: cancelled は二重にキャンセルできない',
  errorMessageOf('cancelled のキャンセル', requestCancel(cancelledOrder, CANCELLED_AT, 'user_request')),
  'cancelled の注文を cancelled にはできません'
);

// --- 課題7: 総仕上げ（確定・金額・集計）---------------------------
checkNumber('課題7: 小計', checkoutNone.summary.subtotal, 3790);
checkNumber('課題7: 割引額（none）', checkoutNone.summary.discountAmount, 0);
checkNumber('課題7: 消費税', checkoutNone.summary.tax, 379);
checkNumber('課題7: 税込商品合計', checkoutNone.summary.totalWithTax, 4169);
checkNumber('課題7: 送料（3000円以上で無料）', checkoutNone.summary.shippingFee, 0);
checkNumber('課題7: 支払総額', checkoutNone.summary.payableAmount, 4169);
checkNumber('課題7: 注文の合計金額', checkoutNone.order.totalAmount.amount, 4169);
checkString('課題7: 引当の結果', describeReservations(checkoutNone.reservations), '1:3点→残21 / 3:1点→残2');

checkNumber('課題7: 割引額（gold 10%）', checkoutGold.summary.discountAmount, 379);
checkNumber('課題7: 割引後小計', checkoutGold.summary.discountedTotal, 3411);
checkNumber('課題7: 消費税（gold）', checkoutGold.summary.tax, 341);
checkNumber('課題7: 支払総額（gold）', checkoutGold.summary.payableAmount, 3752);

checkNumber('課題7: 小計（石けん2点）', checkoutSmall.summary.subtotal, 960);
checkNumber('課題7: 税込商品合計（石けん2点）', checkoutSmall.summary.totalWithTax, 1056);
checkNumber('課題7: 送料（3000円未満）', checkoutSmall.summary.shippingFee, 500);
checkNumber('課題7: 支払総額（石けん2点）', checkoutSmall.summary.payableAmount, 1556);

checkString(
  '課題7: 空のカートは確定できない',
  errorMessageOf(
    '空のカートの確定',
    checkout(Cart.empty(1), CATALOG, { orderId: 'ORD-9999', rank: 'none', now: PLACED_AT })
  ),
  'カートが空です。商品を追加してください'
);
const shortageMessage = errorMessageOf(
  '在庫不足の確定',
  checkout(cartMug4, CATALOG, { orderId: 'ORD-9998', rank: 'none', now: PLACED_AT })
);
checkString(
  '課題7: 在庫不足では確定できない',
  shortageMessage,
  'マグカップの在庫が足りません（希望 4点 / 在庫 3点）'
);

const orders: readonly Order[] = [pendingOrder, paidGoldOrder, shippedOrder, cancelledOrder];
const orderSummary = summarizeOrders(orders);
checkString(
  '課題7: 集計',
  describeOrderSummary(orderSummary),
  '件数 4 / pending 1 / paid 1 / shipped 1 / cancelled 1 / 売上 5308円 / 未払い 4169円'
);
checkNumber('課題7: 売上の内訳（3752 + 1556）', orderSummary.salesAmount.amount, 3752 + 1556);
checkNumber('課題7: 0件の集計', summarizeOrders([]).salesAmount.amount, 0);
checkString(
  '課題7: すべての注文を1行で表示できる',
  orders.map((order) => orderStatusOf(order)).join(','),
  'pending,paid,shipped,cancelled'
);

// ===== 16. 結果の報告 ==============================================

console.log('=== ミニ雑貨ショップ ドメインモデル ===');
console.log(`カート: ${cart.lineCount}明細 / ${cart.itemCount}点 / 小計${cart.subtotal.amount}円`);
console.log(describeOrder(pendingOrder));
console.log(describeOrder(paidOrder));
console.log(describeOrder(shippedOrder));
console.log(describeOrder(cancelledOrder));
console.log(`在庫不足: ${shortageMessage}`);
console.log(`集計: ${describeOrderSummary(orderSummary)}`);

if (failedCount > 0) {
  console.error(`mid02: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('mid02: ok');
