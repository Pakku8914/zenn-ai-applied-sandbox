/**
 * セッション15「クラスとオブジェクト指向」の検証スクリプト。
 *
 * 本文（049）と練習問題の解答（051）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * 検証の中心は Cart クラスの不変条件と、private と # の違いの実行時の証明。
 *
 * 実行: docker compose exec ts npx tsx src/session15/verify.ts
 */

// ---------------------------------------------------------------------------
// 共通の定数（本書は金額を整数の円で扱う）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;
/** 1つの明細に入れられる数量の上限（S15 で確定） */
const MAX_CART_QUANTITY = 10;

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 "${expected}" / 実際 "${actual}"`);
    failedCount += 1;
  }
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

/** 指定したメッセージのエラーで止まることを確認する */
function checkThrows(label: string, run: () => void, expectedMessage: string): void {
  try {
    run();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message !== expectedMessage) {
      console.error(`NG: ${label} — 期待メッセージ "${expectedMessage}" / 実際 "${message}"`);
      failedCount += 1;
    }
    return;
  }
  console.error(`NG: ${label} — エラーが発生しませんでした`);
  failedCount += 1;
}

/** 実行時に TypeError で止まることを確認する（メッセージは実行環境依存なので見ない） */
function checkThrowsTypeError(label: string, run: () => void): void {
  try {
    run();
  } catch (error) {
    if (!(error instanceof TypeError)) {
      console.error(`NG: ${label} — TypeError ではありませんでした: ${String(error)}`);
      failedCount += 1;
    }
    return;
  }
  console.error(`NG: ${label} — エラーが発生しませんでした`);
  failedCount += 1;
}

// ---------------------------------------------------------------------------
// この章で使う共通データ（本文「この章で使う共通データ」と同じ）
// requirements.md の商品マスタから、この章で使わない
// description / imageUrl を省いたもの。値は変えていない。
// ---------------------------------------------------------------------------
type Product = { id: number; name: string; price: number; stock: number; categoryId: number };
type CartItem = { id: number; userId: number; productId: number; quantity: number };
type CartItemWithProduct = CartItem & { product: Product };
type MemberRank = 'gold' | 'silver' | 'bronze' | 'none';
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

const products: readonly Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

const productById = new Map<number, Product>();
for (const product of products) {
  productById.set(product.id, product);
}

const soap: Product = { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 };
const mug: Product = { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 };
const cloth: Product = { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 };

const calcLineTotal = (price: number, quantity: number): number => price * quantity;

/** 明細の小計（税抜・整数円）。クラスの中の配列をそのまま渡せるよう readonly で受ける */
function calcSubtotal(lines: readonly CartItemWithProduct[]): number {
  return lines.reduce((total, line) => total + calcLineTotal(line.product.price, line.quantity), 0);
}

/** 送料。判定基準は税込商品合計 */
function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** 送料無料まであといくらか */
function calcRemainingForFreeShipping(totalWithTax: number): number {
  return Math.max(0, FREE_SHIPPING_THRESHOLD - totalWithTax);
}

/** 支払いの内訳（本書共通の計算手順1〜7） */
function buildPaymentSummary(lines: readonly CartItemWithProduct[], rule: DiscountRule): PaymentSummary {
  const subtotal = calcSubtotal(lines); // 手順1
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

function resolveMemberRank(totalSpent: number): MemberRank {
  if (totalSpent >= 50000) return 'gold';
  if (totalSpent >= 20000) return 'silver';
  if (totalSpent >= 5000) return 'bronze';
  return 'none';
}

// S14 で学んだ Record<MemberRank, number> で割引率の表を持つ
const DISCOUNT_PERCENT_BY_RANK: Record<MemberRank, number> = {
  gold: 10,
  silver: 5,
  bronze: 3,
  none: 0,
};

function discountPercentByRank(rank: MemberRank): number {
  return DISCOUNT_PERCENT_BY_RANK[rank];
}

const noDiscount: DiscountRule = () => 0;

// ---------------------------------------------------------------------------
// 本文 1節：不変条件が守れないカート（type + 関数）
// ---------------------------------------------------------------------------
type PlainCart = { userId: number; lines: CartItemWithProduct[] };

/** 数量を検査してから明細を足す（同じ商品をまとめる処理も、本来はこの中に書く） */
function addToPlainCart(cart: PlainCart, product: Product, quantity: number): PlainCart {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_CART_QUANTITY) {
    throw new RangeError(`数量は1以上${MAX_CART_QUANTITY}以下の整数で指定してください: ${quantity}`);
  }

  const nextId = cart.lines.reduce((max, line) => Math.max(max, line.id), 0) + 1;
  const newLine: CartItemWithProduct = {
    id: nextId,
    userId: cart.userId,
    productId: product.id,
    quantity,
    product,
  };
  return { ...cart, lines: [...cart.lines, newLine] };
}

function bodyPlainCart(): string {
  const emptyPlainCart: PlainCart = { userId: 1, lines: [] };
  const afterAdd = addToPlainCart(emptyPlainCart, soap, 2);
  const before = `正しい入口を通った: ${afterAdd.lines.length}明細 / 小計${calcSubtotal(afterAdd.lines)}円`;

  // 関数を通らずに直接 push できてしまう（不変条件が壊れる）
  afterAdd.lines.push({ id: 99, userId: 1, productId: 1, quantity: 999, product: soap });
  const after = `外から push した後: ${afterAdd.lines.length}明細 / 小計${calcSubtotal(afterAdd.lines)}円`;

  return [before, after].join('\n');
}

checkString(
  '本文1節: type + 関数では push を止められない',
  bodyPlainCart(),
  '正しい入口を通った: 1明細 / 小計960円\n外から push した後: 2明細 / 小計480480円'
);
checkNumber('本文1節: 不正な明細の小計', 480 * 2 + 480 * 999, 480480);

// 関数を通れば数量の検査は効く
checkThrows(
  '本文1節: 入口を通れば上限は守られる',
  () => {
    addToPlainCart({ userId: 1, lines: [] }, soap, 11);
  },
  '数量は1以上10以下の整数で指定してください: 11'
);

// ---------------------------------------------------------------------------
// 本文 2節：クラスの基本形（パラメータプロパティ版）
// ---------------------------------------------------------------------------
class ShopItem {
  constructor(
    readonly name: string,
    readonly price: number
  ) {}

  /** 税込価格（円・整数） */
  taxIncludedPrice(): number {
    return this.price + Math.floor(this.price * TAX_RATE);
  }

  describe(): string {
    return `${this.name}：${this.price}円（税込 ${this.taxIncludedPrice()}円）`;
  }
}

function bodyShopItem(): string {
  const soapItem = new ShopItem('ラベンダーの石けん', 480);
  const mugItem = new ShopItem('マグカップ', 2350);

  return [
    soapItem.describe(),
    mugItem.describe(),
    `soapItem は ShopItem か: ${soapItem instanceof ShopItem}`,
  ].join('\n');
}

checkString(
  '本文2節: クラスの基本形',
  bodyShopItem(),
  'ラベンダーの石けん：480円（税込 528円）\n' +
    'マグカップ：2350円（税込 2585円）\n' +
    'soapItem は ShopItem か: true'
);

// ---------------------------------------------------------------------------
// 本文 3節：private（型の壁だけ）と #（実行時の壁）
// ---------------------------------------------------------------------------
class CheckoutSession {
  constructor(
    readonly orderId: string,
    private readonly secret: string
  ) {}

  maskedSecret(): string {
    return `${this.secret.slice(0, 3)}***`;
  }
}

class SafeCheckoutSession {
  #secret: string;

  constructor(
    readonly orderId: string,
    secret: string
  ) {
    this.#secret = secret;
  }

  maskedSecret(): string {
    return `${this.#secret.slice(0, 3)}***`;
  }

  /** 同じクラスの中からなら # フィールドの有無を調べられる */
  static isSession(value: object): boolean {
    return #secret in value;
  }

  /**
   * クラスの中からなら他のインスタンスの # フィールドを読める。
   * 宣言していないオブジェクトを渡すと実行時に TypeError になることを確認するために使う。
   */
  static readSecretUnsafely(target: SafeCheckoutSession): string {
    return target.#secret;
  }
}

const bodySession = new CheckoutSession('ORD-1001', 'tok_abcdef');
const bodySafeSession = new SafeCheckoutSession('ORD-1002', 'tok_abcdef');

checkString('本文3節: private のマスク', bodySession.maskedSecret(), 'tok***');
checkString('本文3節: # のマスク', bodySafeSession.maskedSecret(), 'tok***');

// private は型チェック時にしか存在しない（ブラケットアクセスで読める）
checkString('本文3節: private はブラケットアクセスで破れる', bodySession['secret'], 'tok_abcdef');

// private は型アサーションでも破れる
type SecretPeek = { secret: string };
checkString(
  '本文3節: private は型アサーションで破れる',
  (bodySession as unknown as SecretPeek).secret,
  'tok_abcdef'
);

// private は JSON にそのまま現れる（Bad 側の実演）
checkString(
  '本文3節 Bad: private は JSON に出る',
  JSON.stringify(bodySession),
  '{"orderId":"ORD-1001","secret":"tok_abcdef"}'
);

// # は通常のプロパティではないので JSON にも Object.keys にも現れない（Good 側の実演）
checkString(
  '本文3節 Good: # は JSON に出ない',
  JSON.stringify(bodySafeSession),
  '{"orderId":"ORD-1002"}'
);
checkString('本文3節: # は Object.keys に出ない', Object.keys(bodySafeSession).join(','), 'orderId');

// # は実行時の壁。宣言していないオブジェクトから読もうとすると TypeError になる
const fakeSession = { orderId: 'ORD-9999' } as unknown as SafeCheckoutSession;
checkThrowsTypeError('本文3節: # は実行時に守られる（TypeError）', () => {
  SafeCheckoutSession.readSecretUnsafely(fakeSession);
});
// 本物なら読める（同じ経路で成功することを示して、上の失敗が経路のせいでないことを確認する）
checkString(
  '本文3節: # は本物からは読める',
  SafeCheckoutSession.readSecretUnsafely(bodySafeSession),
  'tok_abcdef'
);
checkBoolean('本文3節: brand check（本物）', SafeCheckoutSession.isSession(bodySafeSession), true);
checkBoolean(
  '本文3節: brand check（似せたオブジェクト）',
  SafeCheckoutSession.isSession({ orderId: 'ORD-1003' }),
  false
);

// ---------------------------------------------------------------------------
// 補足：readonly とゲッターで不変条件を守る小さな例（OrderLine）
// 本文4節では「コンストラクタで検査 / readonly / ゲッター」の3点を Cart で示すため、
// この例は本文からは外してある。検証だけ残す。
// ---------------------------------------------------------------------------
class OrderLine {
  constructor(
    readonly productId: number,
    readonly productName: string,
    readonly unitPrice: number,
    readonly quantity: number
  ) {
    if (!Number.isInteger(unitPrice) || unitPrice < 1) {
      throw new RangeError(`単価は1以上の整数で指定してください: ${unitPrice}`);
    }
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_CART_QUANTITY) {
      throw new RangeError(
        `数量は1以上${MAX_CART_QUANTITY}以下の整数で指定してください: ${quantity}`
      );
    }
  }

  get lineTotal(): number {
    return calcLineTotal(this.unitPrice, this.quantity);
  }

  get displayLine(): string {
    return `${this.productName} ${this.unitPrice}円 × ${this.quantity}点 = ${this.lineTotal}円`;
  }
}

checkString(
  'OrderLine: ゲッターで整形した1行',
  new OrderLine(3, 'マグカップ', 2350, 2).displayLine,
  'マグカップ 2350円 × 2点 = 4700円'
);
checkNumber('OrderLine: 明細金額', new OrderLine(3, 'マグカップ', 2350, 2).lineTotal, 4700);
checkThrows(
  'OrderLine: 数量0 は作れない',
  () => {
    new OrderLine(3, 'マグカップ', 2350, 0);
  },
  '数量は1以上10以下の整数で指定してください: 0'
);
checkThrows(
  'OrderLine: 数量11 は作れない',
  () => {
    new OrderLine(3, 'マグカップ', 2350, 11);
  },
  '数量は1以上10以下の整数で指定してください: 11'
);
checkThrows(
  'OrderLine: 単価0 は作れない',
  () => {
    new OrderLine(3, 'マグカップ', 0, 1);
  },
  '単価は1以上の整数で指定してください: 0'
);

// ---------------------------------------------------------------------------
// 本文 5節：Cart クラス
// has() と fromItems() は問題4で追加する分。出力は本文の Cart と同じになる。
// ---------------------------------------------------------------------------
class Cart {
  private readonly lines: readonly CartItemWithProduct[];

  private constructor(
    readonly userId: number,
    lines: readonly CartItemWithProduct[]
  ) {
    this.lines = lines;
  }

  static empty(userId: number): Cart {
    return new Cart(userId, []);
  }

  /** 保存済みの明細から復元する。商品が見つからない明細は捨てる（問題4） */
  static fromItems(userId: number, items: readonly CartItem[], byId: Map<number, Product>): Cart {
    let cart = Cart.empty(userId);
    for (const item of items) {
      const product = byId.get(item.productId);
      if (product === undefined) {
        continue;
      }
      cart = cart.add(product, item.quantity);
    }
    return cart;
  }

  private static validateQuantity(quantity: number): void {
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_CART_QUANTITY) {
      throw new RangeError(
        `数量は1以上${MAX_CART_QUANTITY}以下の整数で指定してください: ${quantity}`
      );
    }
  }

  /** 読み取り専用のコピーを返す（防御的コピー） */
  get items(): readonly CartItemWithProduct[] {
    return [...this.lines];
  }

  get lineCount(): number {
    return this.lines.length;
  }

  get itemCount(): number {
    return this.lines.reduce((total, line) => total + line.quantity, 0);
  }

  /** 小計は常に明細から計算する */
  get subtotal(): number {
    return calcSubtotal(this.lines);
  }

  get isEmpty(): boolean {
    return this.lines.length === 0;
  }

  /** 問題4で追加 */
  has(productId: number): boolean {
    return this.lines.some((line) => line.productId === productId);
  }

  add(product: Product, quantity: number): Cart {
    const existing = this.lines.find((line) => line.productId === product.id);

    if (existing !== undefined) {
      return this.changeQuantity(product.id, existing.quantity + quantity);
    }

    Cart.validateQuantity(quantity);
    const newLine: CartItemWithProduct = {
      id: this.nextLineId(),
      userId: this.userId,
      productId: product.id,
      quantity,
      product,
    };
    return new Cart(this.userId, [...this.lines, newLine]);
  }

  changeQuantity(productId: number, quantity: number): Cart {
    Cart.validateQuantity(quantity);
    if (!this.has(productId)) {
      throw new Error(`カートにない商品です: productId=${productId}`);
    }
    const nextLines = this.lines.map((line) =>
      line.productId === productId ? { ...line, quantity } : line
    );
    return new Cart(this.userId, nextLines);
  }

  remove(productId: number): Cart {
    return new Cart(
      this.userId,
      this.lines.filter((line) => line.productId !== productId)
    );
  }

  summary(rule: DiscountRule): PaymentSummary {
    return buildPaymentSummary(this.lines, rule);
  }

  private nextLineId(): number {
    return this.lines.reduce((max, line) => Math.max(max, line.id), 0) + 1;
  }
}

const emptyCart = Cart.empty(1);
const withSoap = emptyCart.add(soap, 2);
const withMug = withSoap.add(mug, 1);
/** 石けん3点 + マグカップ1点 = 小計3790円（本文5節・7節・9節で使う） */
const merged = withMug.add(soap, 1);

function bodyCart(): string {
  const summary = merged.summary(noDiscount);
  const smallSummary = withSoap.summary(noDiscount);

  return [
    `空のカート: ${emptyCart.lineCount}明細 / ${emptyCart.itemCount}点 / 小計${emptyCart.subtotal}円`,
    `石けん2点: ${withSoap.lineCount}明細 / ${withSoap.itemCount}点 / 小計${withSoap.subtotal}円`,
    `+マグカップ: ${withMug.lineCount}明細 / ${withMug.itemCount}点 / 小計${withMug.subtotal}円`,
    `+石けん1点: ${merged.lineCount}明細 / ${merged.itemCount}点 / 小計${merged.subtotal}円`,
    `最初のカートは変わらない: ${emptyCart.lineCount}明細`,
    `小計${summary.subtotal}円 / 消費税${summary.tax}円 / 送料${summary.shippingFee}円 / お支払い${summary.payableAmount}円`,
    `石けんだけ: お支払い${smallSummary.payableAmount}円（送料${smallSummary.shippingFee}円）`,
  ].join('\n');
}

// 本文4節に載せた2つのミニ例（チェーンで作る形）
const bodyChainedCart = Cart.empty(1).add(soap, 2).add(mug, 1).add(soap, 1);
checkString(
  '本文4節: 同じ商品は1明細にまとまる',
  `${bodyChainedCart.lineCount}明細 / ${bodyChainedCart.itemCount}点 / 小計${bodyChainedCart.subtotal}円`,
  '2明細 / 4点 / 小計3790円'
);
const bodyChainedSummary = bodyChainedCart.summary(noDiscount);
checkString(
  '本文4節: 支払いの内訳',
  `小計${bodyChainedSummary.subtotal}円 / 消費税${bodyChainedSummary.tax}円 / 送料${bodyChainedSummary.shippingFee}円 / お支払い${bodyChainedSummary.payableAmount}円`,
  '小計3790円 / 消費税379円 / 送料0円 / お支払い4169円'
);

checkString(
  '本文4節: Cart の操作（段階的に作った場合も同じ）',
  bodyCart(),
  '空のカート: 0明細 / 0点 / 小計0円\n' +
    '石けん2点: 1明細 / 2点 / 小計960円\n' +
    '+マグカップ: 2明細 / 3点 / 小計3310円\n' +
    '+石けん1点: 2明細 / 4点 / 小計3790円\n' +
    '最初のカートは変わらない: 0明細\n' +
    '小計3790円 / 消費税379円 / 送料0円 / お支払い4169円\n' +
    '石けんだけ: お支払い1556円（送料500円）'
);

// --- 不変条件1：同じ商品は1明細にまとまる -------------------------------------
checkNumber('不変条件1: 同じ商品を2回追加しても1明細', merged.lineCount, 2);
checkNumber('不変条件1: 数量は合算される', merged.itemCount, 4);
const mergedSoapLine = merged.items.find((line) => line.productId === 1);
checkNumber(
  '不変条件1: 石けんの明細は1本で3点',
  mergedSoapLine === undefined ? -1 : mergedSoapLine.quantity,
  3
);
checkNumber(
  '不変条件1: 石けんの明細は重複していない',
  merged.items.filter((line) => line.productId === 1).length,
  1
);

// --- 不変条件2：数量は1以上 MAX_CART_QUANTITY 以下の整数 ----------------------
checkThrows(
  '不変条件2: 上限超えは拒否（3 + 8 = 11）',
  () => {
    merged.add(soap, 8);
  },
  '数量は1以上10以下の整数で指定してください: 11'
);
checkThrows(
  '不変条件2: 0点は拒否',
  () => {
    Cart.empty(1).add(mug, 0);
  },
  '数量は1以上10以下の整数で指定してください: 0'
);
checkThrows(
  '不変条件2: マイナスは拒否',
  () => {
    Cart.empty(1).add(mug, -1);
  },
  '数量は1以上10以下の整数で指定してください: -1'
);
checkThrows(
  '不変条件2: 小数は拒否',
  () => {
    Cart.empty(1).add(mug, 1.5);
  },
  '数量は1以上10以下の整数で指定してください: 1.5'
);
checkThrows(
  '不変条件2: changeQuantity でも上限を守る',
  () => {
    merged.changeQuantity(1, 11);
  },
  '数量は1以上10以下の整数で指定してください: 11'
);
checkThrows(
  '不変条件2: カートにない商品の数量は変えられない',
  () => {
    merged.changeQuantity(4, 1);
  },
  'カートにない商品です: productId=4'
);
// 上限ぴったりは通る（境界値）
checkNumber('不変条件2: 上限ぴったりは通る', Cart.empty(1).add(mug, 10).itemCount, 10);

// --- 不変条件3：合計は常に明細から再計算される -------------------------------
const changedForTotal = merged.changeQuantity(1, 5);
checkNumber('不変条件3: 数量変更が小計に反映される', changedForTotal.subtotal, 480 * 5 + 2350);
checkNumber('不変条件3: 変更前の小計は変わらない', merged.subtotal, 3790);
checkNumber(
  '不変条件3: 小計は明細から計算した値と一致する',
  merged.subtotal,
  calcSubtotal(merged.items)
);
checkNumber('不変条件3: 削除後も小計が追随する', merged.remove(3).subtotal, 1440);
checkBoolean('不変条件3: remove は冪等（無い商品でも壊れない）', merged.remove(99).subtotal === 3790, true);

// --- 防御的コピー：外に出した配列を書き換えても内部は壊れない ---------------
const snapshot = merged.items;
// 型の上では readonly なので push できない。型アサーションで破ってもコピーなので本体は無事
(snapshot as CartItemWithProduct[]).push({ id: 99, userId: 1, productId: 1, quantity: 999, product: soap });
checkNumber('防御的コピー: コピー側は増える', snapshot.length, 3);
checkNumber('防御的コピー: カート本体の明細数は変わらない', merged.lineCount, 2);
checkNumber('防御的コピー: カート本体の点数は変わらない', merged.itemCount, 4);
checkNumber('防御的コピー: カート本体の小計は変わらない', merged.subtotal, 3790);
// 呼ぶたびに新しい配列を返す（同じ参照を配らない）
checkBoolean('防御的コピー: 毎回別の配列を返す', merged.items !== merged.items, true);

// --- Bad：ゲッターが内部配列をそのまま返すと壊れる ---------------------------
class LeakyCart {
  private readonly lines: CartItemWithProduct[] = [];

  get items(): CartItemWithProduct[] {
    return this.lines; // 内部の配列そのものを返してしまう
  }

  add(line: CartItemWithProduct): void {
    this.lines.push(line);
  }

  get itemCount(): number {
    return this.lines.reduce((total, line) => total + line.quantity, 0);
  }
}

function bodyLeakyCart(): string {
  const leaky = new LeakyCart();
  leaky.add({ id: 1, userId: 1, productId: 1, quantity: 2, product: soap });
  const before = `追加後: ${leaky.itemCount}点`;

  const stolen = leaky.items; // 内部への参照が外に出た
  stolen.push({ id: 2, userId: 1, productId: 1, quantity: 999, product: soap });

  return [before, `外から push した後: ${leaky.itemCount}点`].join('\n');
}

checkString(
  '本文5節 Bad: 内部配列を返すと外から壊せる',
  bodyLeakyCart(),
  '追加後: 2点\n外から push した後: 1001点'
);

// ---------------------------------------------------------------------------
// 本文 5節（発展）：ジェネリッククラス
// ---------------------------------------------------------------------------
class Box<T> {
  constructor(
    readonly label: string,
    private readonly content: T
  ) {}

  describe(format: (content: T) => string): string {
    return `${this.label} = ${format(this.content)}`;
  }
}

checkString(
  '本文5節: ジェネリッククラス',
  new Box<number>('価格', 480).describe((price) => `${price}円`),
  '価格 = 480円'
);

// ---------------------------------------------------------------------------
// 本文 6節：static の使いどころ（Bad: static だけのクラス / Good: 関数）
// ---------------------------------------------------------------------------
class ShippingUtils {
  static remaining(totalWithTax: number): number {
    return Math.max(0, FREE_SHIPPING_THRESHOLD - totalWithTax);
  }
}

checkString(
  '本文6節 Bad: static だけのクラス',
  `送料無料まであと${ShippingUtils.remaining(1056)}円`,
  '送料無料まであと1944円'
);
checkString(
  '本文6節 Good: ただの関数',
  `送料無料まであと${calcRemainingForFreeShipping(1056)}円`,
  '送料無料まであと1944円'
);
checkNumber('本文6節: 税込商品合計1056円', withSoap.summary(noDiscount).totalWithTax, 1056);
checkNumber('本文6節: 送料無料まで満たしている場合は0', calcRemainingForFreeShipping(3312), 0);

// ---------------------------------------------------------------------------
// 本文 7節：継承（抽象クラス）
// RankDiscount は問題5で追加する分。
// ---------------------------------------------------------------------------
/** 割引の「形」だけを決める約束（本文6節で implements の相手として使う） */
interface DiscountPolicy {
  readonly label: string;
  amountFor(subtotal: number): number;
}

abstract class Discount implements DiscountPolicy {
  constructor(readonly label: string) {}

  /** 共通の不変条件：割引額は小計を超えない。ここに1回だけ書く */
  amountFor(subtotal: number): number {
    return Math.min(this.rawAmount(subtotal), subtotal);
  }

  protected abstract rawAmount(subtotal: number): number;

  /** 既存の関数型 DiscountRule への橋渡し */
  toRule(): DiscountRule {
    return (subtotal) => this.amountFor(subtotal);
  }
}

class PercentDiscount extends Discount {
  constructor(readonly percent: number) {
    super(`${percent}%OFF`);
  }

  protected override rawAmount(subtotal: number): number {
    return Math.floor((subtotal * this.percent) / 100);
  }
}

class FixedAmountDiscount extends Discount {
  constructor(readonly amount: number) {
    super(`${amount}円OFF`);
  }

  protected override rawAmount(): number {
    return this.amount;
  }
}

/** 会員ランクから率を決める（問題5） */
class RankDiscount extends PercentDiscount {
  constructor(readonly rank: MemberRank) {
    super(discountPercentByRank(rank));
  }
}

/** 率の割引に上限額を足す。親の計算結果を super で受け取る */
class CappedPercentDiscount extends PercentDiscount {
  constructor(
    percent: number,
    readonly maxAmount: number
  ) {
    super(percent);
  }

  override amountFor(subtotal: number): number {
    return Math.min(super.amountFor(subtotal), this.maxAmount);
  }
}

function describeDiscount(discount: Discount): string {
  // サブクラスから先に判定する（順番を逆にすると上位のクラスに吸収される）
  if (discount instanceof RankDiscount) {
    return `${discount.label}（会員ランク: ${discount.rank}）`;
  }
  if (discount instanceof CappedPercentDiscount) {
    return `${discount.label}（上限: ${discount.maxAmount}円）`;
  }
  if (discount instanceof PercentDiscount) {
    return `${discount.label}（率: ${discount.percent}%）`;
  }
  if (discount instanceof FixedAmountDiscount) {
    return `${discount.label}（固定額: ${discount.amount}円）`;
  }
  return discount.label;
}

/** 本文6節の describeDiscount（分岐は2つ。どのサブクラスでもなければラベルだけ返る） */
function describeDiscountBody(discount: Discount): string {
  if (discount instanceof CappedPercentDiscount) {
    return `${discount.label}（上限: ${discount.maxAmount}円）`;
  }
  if (discount instanceof PercentDiscount) {
    return `${discount.label}（率: ${discount.percent}%）`;
  }
  return discount.label;
}

function bodyDiscount(): string {
  const discounts: readonly Discount[] = [
    new PercentDiscount(10),
    new FixedAmountDiscount(500),
    new CappedPercentDiscount(10, 300),
  ];

  const lines = discounts.map(
    (discount) => `${describeDiscountBody(discount)} → ${discount.amountFor(3790)}円引き`
  );

  lines.push(`小計200円に500円OFF → ${new FixedAmountDiscount(500).amountFor(200)}円引き`);

  const goldSummary = merged.summary(new PercentDiscount(10).toRule());
  lines.push(
    `10%OFF のお支払い: ${goldSummary.payableAmount}円（割引${goldSummary.discountAmount}円）`
  );

  return lines.join('\n');
}

checkString(
  '本文6節: 継承した割引クラス',
  bodyDiscount(),
  '10%OFF（率: 10%） → 379円引き\n' +
    '500円OFF → 500円引き\n' +
    '10%OFF（上限: 300円） → 300円引き\n' +
    '小計200円に500円OFF → 200円引き\n' +
    '10%OFF のお支払い: 3752円（割引379円）'
);

// instanceof の順番を逆にすると上限つきの割引が「ただの率の割引」になる
function describeDiscountWrongOrder(discount: Discount): string {
  if (discount instanceof PercentDiscount) {
    return `${discount.label}（率: ${discount.percent}%）`;
  }
  return discount.label;
}

checkString(
  '本文6節: instanceof の順番を誤ると判別できない',
  describeDiscountWrongOrder(new CappedPercentDiscount(10, 300)),
  '10%OFF（率: 10%）'
);

// 支払総額の内訳（本文に書いた数値）
checkNumber('本文6節 手順2 割引額', new PercentDiscount(10).amountFor(3790), 379);
checkNumber('本文6節 手順3 割引後小計', 3790 - 379, 3411);
checkNumber('本文6節 手順4 消費税', Math.floor(3411 * TAX_RATE), 341);
checkNumber('本文6節 手順5 税込商品合計', 3411 + 341, 3752);
checkNumber('本文6節 手順6 送料', calcShippingFee(3752), 0);

// ---------------------------------------------------------------------------
// 本文 8節：implements（形だけの約束）
// ---------------------------------------------------------------------------
class CouponDiscount implements DiscountPolicy {
  readonly label: string;

  constructor(
    readonly code: string,
    private readonly amount: number
  ) {
    this.label = `クーポン ${code}`;
  }

  amountFor(subtotal: number): number {
    // 継承していないので、クリップを自分で書く必要がある
    return Math.min(this.amount, subtotal);
  }
}

/** クラスでなくても形が合っていれば DiscountPolicy として通る（構造的部分型） */
const campaignPolicy: DiscountPolicy = {
  label: '春の全品100円OFF',
  amountFor: (subtotal) => Math.min(100, subtotal),
};

function describePolicy(subtotal: number, policy: DiscountPolicy): string {
  return `${policy.label}: -${policy.amountFor(subtotal)}円`;
}

const coupon = new CouponDiscount('SPRING', 300);

checkString(
  '補足（本文6節の表 / 練習問題6）:DiscountPolicy を満たす3種類',
  [
    describePolicy(3790, new PercentDiscount(10)),
    describePolicy(3790, coupon),
    describePolicy(3790, campaignPolicy),
  ].join('\n'),
  '10%OFF: -379円\nクーポン SPRING: -300円\n春の全品100円OFF: -100円'
);

// メソッドだけを取り出すと this を失う（型は通るのに実行時に落ちる）
const looseRule: DiscountRule = coupon.amountFor;
checkThrowsTypeError('よくあるエラー: メソッドを取り出すと this を失う', () => {
  looseRule(3790);
});
const safeRule: DiscountRule = (subtotal) => coupon.amountFor(subtotal);
checkNumber('よくあるエラー: アロー関数で包めば動く', safeRule(3790), 300);

// ---------------------------------------------------------------------------
// 本文 9節：継承よりコンポジション
// ---------------------------------------------------------------------------
class CombinedDiscount implements DiscountPolicy {
  readonly label: string;

  constructor(private readonly policies: readonly DiscountPolicy[]) {
    this.label = policies.map((policy) => policy.label).join(' + ');
  }

  amountFor(subtotal: number): number {
    const total = this.policies.reduce((sum, policy) => sum + policy.amountFor(subtotal), 0);
    return Math.min(total, subtotal); // 合算しても小計を超えない
  }
}

function bodyCombined(): string {
  const combined = new CombinedDiscount([new PercentDiscount(10), new FixedAmountDiscount(500)]);
  const combinedSummary = merged.summary((subtotal) => combined.amountFor(subtotal));

  return [
    `${combined.label} → ${combined.amountFor(3790)}円引き`,
    `割引${combinedSummary.discountAmount}円 / 税${combinedSummary.tax}円 / お支払い${combinedSummary.payableAmount}円`,
  ].join('\n');
}

checkString(
  '本文7節: コンポジションで組み合わせる',
  bodyCombined(),
  '10%OFF + 500円OFF → 879円引き\n割引879円 / 税291円 / お支払い3202円'
);
checkNumber('本文7節（合算後） 手順3 割引後小計', 3790 - 879, 2911);
checkNumber('本文7節（合算後） 手順4 消費税', Math.floor(2911 * TAX_RATE), 291);
// クーポンとの組み合わせ（練習問題6で使う形）も同じ仕組みで動く
checkNumber(
  '本文7節: クーポンと組み合わせても合算される',
  new CombinedDiscount([new PercentDiscount(10), coupon]).amountFor(3790),
  679
);

// ---------------------------------------------------------------------------
// 本文 10節：境界を越える値はクラスにしない
// ---------------------------------------------------------------------------
class ProductCard {
  constructor(readonly product: Product) {}

  get displayPrice(): string {
    return `${this.product.price}円`;
  }
}

function formatPrice(product: Product): string {
  return `${product.price}円`;
}

function bodyClassOrNot(): string {
  const card = new ProductCard(soap);
  const json = JSON.stringify(card);

  return [
    `サーバー側: ${card.displayPrice}`,
    `JSON に残るキー: ${Object.keys(JSON.parse(json)).join(' / ')}`,
    `displayPrice は JSON に含まれるか: ${json.includes('displayPrice')}`,
    `関数版 サーバー側: ${formatPrice(soap)}`,
    `関数版 クライアント側: ${formatPrice(JSON.parse(JSON.stringify(soap)))}`,
  ].join('\n');
}

checkString(
  '本文8節: JSON を越えるとゲッターは消える',
  bodyClassOrNot(),
  'サーバー側: 480円\n' +
    'JSON に残るキー: product\n' +
    'displayPrice は JSON に含まれるか: false\n' +
    '関数版 サーバー側: 480円\n' +
    '関数版 クライアント側: 480円'
);

// ---------------------------------------------------------------------------
// よくある誤解：コンストラクタからサブクラスのメソッドを呼ぶと NaN になる
// ---------------------------------------------------------------------------
abstract class BadDiscount {
  readonly preview: number;

  constructor() {
    this.preview = this.rawAmount(1000); // ここでサブクラスのメソッドを呼ぶ
  }

  protected abstract rawAmount(subtotal: number): number;
}

class BadPercentDiscount extends BadDiscount {
  constructor(private readonly percent: number) {
    super(); // super() の時点では this.percent はまだ undefined
  }

  protected override rawAmount(subtotal: number): number {
    return Math.floor((subtotal * this.percent) / 100);
  }
}

const badDiscount = new BadPercentDiscount(10);
checkBoolean('誤解2: コンストラクタから呼ぶと NaN になる', Number.isNaN(badDiscount.preview), true);
checkNumber('誤解2: 初期化後に呼べば正しい値になる', new PercentDiscount(10).amountFor(1000), 100);

// ---------------------------------------------------------------------------
// 問題1：カタログの1件をクラスで表す
// ---------------------------------------------------------------------------
class CatalogItem {
  constructor(
    readonly name: string,
    readonly price: number,
    readonly stock: number
  ) {}

  taxIncludedPrice(): number {
    return this.price + Math.floor(this.price * TAX_RATE);
  }

  get isSoldOut(): boolean {
    return this.stock <= 0;
  }

  canOrder(quantity: number): boolean {
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_CART_QUANTITY) {
      return false;
    }
    return quantity <= this.stock;
  }

  describe(): string {
    const soldOutMark = this.isSoldOut ? ' ← 在庫切れ' : '';
    return `${this.name}：${this.price}円（税込${this.taxIncludedPrice()}円）/ 在庫${this.stock}点${soldOutMark}`;
  }
}

function solveQ1(): string {
  const catalog = products.map(
    (product) => new CatalogItem(product.name, product.price, product.stock)
  );
  const lines = catalog.map((item) => item.describe());

  const mugItem = new CatalogItem('マグカップ', 2350, 3);
  const clothItem = new CatalogItem('リネンのふきん', 990, 0);
  const toteItem = new CatalogItem('コットンのトートバッグ', 2800, 5);

  lines.push(`マグカップを3点注文できる: ${mugItem.canOrder(3)}`);
  lines.push(`マグカップを4点注文できる: ${mugItem.canOrder(4)}`);
  lines.push(`リネンのふきんを1点注文できる: ${clothItem.canOrder(1)}`);
  lines.push(`コットンのトートバッグを11点注文できる: ${toteItem.canOrder(11)}`);

  return lines.join('\n');
}

checkString(
  '問題1: 出力9行',
  solveQ1(),
  'ラベンダーの石けん：480円（税込528円）/ 在庫24点\n' +
    'ハンドクリーム：1800円（税込1980円）/ 在庫12点\n' +
    'マグカップ：2350円（税込2585円）/ 在庫3点\n' +
    'リネンのふきん：990円（税込1089円）/ 在庫0点 ← 在庫切れ\n' +
    'コットンのトートバッグ：2800円（税込3080円）/ 在庫5点\n' +
    'マグカップを3点注文できる: true\n' +
    'マグカップを4点注文できる: false\n' +
    'リネンのふきんを1点注文できる: false\n' +
    'コットンのトートバッグを11点注文できる: false'
);

// 別解：Product をまるごと持つ（コンポジション）でも同じ結果になる
class CatalogItemFromProduct {
  constructor(private readonly product: Product) {}

  get name(): string {
    return this.product.name;
  }

  taxIncludedPrice(): number {
    return this.product.price + Math.floor(this.product.price * TAX_RATE);
  }
}

checkNumber(
  '問題1 別解: Product を持つ形でも同じ税込価格',
  new CatalogItemFromProduct(mug).taxIncludedPrice(),
  2585
);

// ---------------------------------------------------------------------------
// 問題2：private / protected / # を使い分ける
// ---------------------------------------------------------------------------
class InventoryItem {
  #internalCode: string;

  constructor(
    readonly name: string,
    protected readonly stock: number,
    private readonly memo: string,
    internalCode: string
  ) {
    this.#internalCode = internalCode;
  }

  maskedCode(): string {
    return `${this.#internalCode.slice(0, 3)}***`;
  }

  static isInventoryItem(value: object): boolean {
    return #internalCode in value;
  }
}

class ReorderableItem extends InventoryItem {
  constructor(
    name: string,
    stock: number,
    memo: string,
    internalCode: string,
    readonly reorderPoint: number
  ) {
    super(name, stock, memo, internalCode);
  }

  needsReorder(): boolean {
    return this.stock <= this.reorderPoint; // protected なのでサブクラスから読める
  }

  describe(): string {
    const judgement = this.needsReorder() ? '発注必要' : '発注不要';
    return `${this.name} 在庫${this.stock}点（発注点${this.reorderPoint}点）→ ${judgement}`;
  }
}

const q2Mug = new ReorderableItem('マグカップ', 3, '社内メモ', 'MUG-0003', 2);
const q2Cloth = new ReorderableItem('リネンのふきん', 0, '社内メモ', 'CLO-0004', 2);

function solveQ2(): string {
  const json = JSON.stringify(q2Mug);

  return [
    q2Mug.describe(),
    q2Cloth.describe(),
    `maskedCode: ${q2Mug.maskedCode()}`,
    `JSON: ${json}`,
    `Object.keys: ${Object.keys(q2Mug).join(' / ')}`,
    `ブラケットアクセスで private を読めた: ${q2Mug['memo']}`,
    `#internalCode は JSON に含まれるか: ${json.includes('internalCode')}`,
    `isInventoryItem（本物）: ${InventoryItem.isInventoryItem(q2Mug)}`,
    `isInventoryItem（似せたオブジェクト）: ${InventoryItem.isInventoryItem({
      name: 'マグカップ',
      stock: 3,
      memo: '社内メモ',
      reorderPoint: 2,
    })}`,
  ].join('\n');
}

checkString(
  '問題2: 出力9行',
  solveQ2(),
  'マグカップ 在庫3点（発注点2点）→ 発注不要\n' +
    'リネンのふきん 在庫0点（発注点2点）→ 発注必要\n' +
    'maskedCode: MUG***\n' +
    'JSON: {"name":"マグカップ","stock":3,"memo":"社内メモ","reorderPoint":2}\n' +
    'Object.keys: name / stock / memo / reorderPoint\n' +
    'ブラケットアクセスで private を読めた: 社内メモ\n' +
    '#internalCode は JSON に含まれるか: false\n' +
    'isInventoryItem（本物）: true\n' +
    'isInventoryItem（似せたオブジェクト）: false'
);

// ---------------------------------------------------------------------------
// 問題3：readonly とゲッターで会員を表す
// ---------------------------------------------------------------------------
class Member {
  constructor(
    readonly name: string,
    readonly totalSpent: number
  ) {
    if (!Number.isInteger(totalSpent) || totalSpent < 0) {
      throw new RangeError(`累計購入額は0以上の整数で指定してください: ${totalSpent}`);
    }
  }

  get rank(): MemberRank {
    return resolveMemberRank(this.totalSpent);
  }

  get discountPercent(): number {
    return discountPercentByRank(this.rank);
  }

  get description(): string {
    return `${this.name}さん：累計${this.totalSpent}円 → ${this.rank}（${this.discountPercent}%OFF）`;
  }

  discountAmountFor(subtotal: number): number {
    return Math.floor((subtotal * this.discountPercent) / 100);
  }
}

function solveQ3(): string {
  const members: readonly Member[] = [
    new Member('田中', 62000),
    new Member('鈴木', 25000),
    new Member('佐藤', 8000),
    new Member('高橋', 1000),
  ];

  return members
    .map((member) => `${member.description}/ 小計3790円なら${member.discountAmountFor(3790)}円引き`)
    .join('\n');
}

checkString(
  '問題3: 出力4行',
  solveQ3(),
  '田中さん：累計62000円 → gold（10%OFF）/ 小計3790円なら379円引き\n' +
    '鈴木さん：累計25000円 → silver（5%OFF）/ 小計3790円なら189円引き\n' +
    '佐藤さん：累計8000円 → bronze（3%OFF）/ 小計3790円なら113円引き\n' +
    '高橋さん：累計1000円 → none（0%OFF）/ 小計3790円なら0円引き'
);

checkThrows(
  '問題3: マイナスは作れない',
  () => {
    new Member('誤り', -1);
  },
  '累計購入額は0以上の整数で指定してください: -1'
);
checkThrows(
  '問題3: 小数は作れない',
  () => {
    new Member('誤り', 1000.5);
  },
  '累計購入額は0以上の整数で指定してください: 1000.5'
);
// 割引額の内訳（解答の表に書いた数値）
checkNumber('問題3: silver の割引額', Math.floor((3790 * 5) / 100), 189);
checkNumber('問題3: bronze の割引額', Math.floor((3790 * 3) / 100), 113);
// ランクはフィールドに持たないので、累計と食い違わない
checkString('問題3: しきい値ちょうどは gold', new Member('境界', 50000).rank, 'gold');
checkString('問題3: しきい値の1円下は silver', new Member('境界', 49999).rank, 'silver');

// ---------------------------------------------------------------------------
// 問題4：Cart クラスを完成させる（Cart は本文5節の定義を再利用）
// ---------------------------------------------------------------------------
const savedItems: readonly CartItem[] = [
  { id: 1, userId: 1, productId: 1, quantity: 2 },
  { id: 2, userId: 1, productId: 3, quantity: 1 },
];

const describeCart = (label: string, cart: Cart): string =>
  `${label}: ${cart.lineCount}明細 / ${cart.itemCount}点 / 小計${cart.subtotal}円`;

const q4Restored = Cart.fromItems(1, savedItems, productById);
const q4Added = q4Restored.add(soap, 1);
const q4WithCloth = q4Added.add(cloth, 1);
const q4RemovedMug = q4WithCloth.remove(3);
const q4Changed = q4RemovedMug.changeQuantity(1, 5);

function solveQ4(): string {
  return [
    describeCart('復元', q4Restored),
    describeCart('石けんを1点追加', q4Added),
    describeCart('ふきんを1点追加', q4WithCloth),
    describeCart('マグカップを削除', q4RemovedMug),
    describeCart('石けんの数量を5に変更', q4Changed),
    `has(1)=${q4Changed.has(1)} / has(3)=${q4Changed.has(3)}`,
    `お支払い金額: ${q4Changed.summary(noDiscount).payableAmount}円`,
  ].join('\n');
}

checkString(
  '問題4: 出力7行',
  solveQ4(),
  '復元: 2明細 / 3点 / 小計3310円\n' +
    '石けんを1点追加: 2明細 / 4点 / 小計3790円\n' +
    'ふきんを1点追加: 3明細 / 5点 / 小計4780円\n' +
    'マグカップを削除: 2明細 / 4点 / 小計2430円\n' +
    '石けんの数量を5に変更: 2明細 / 6点 / 小計3390円\n' +
    'has(1)=true / has(3)=false\n' +
    'お支払い金額: 3729円'
);

checkThrows(
  '問題4: 上限オーバー（5 + 8 = 13）',
  () => {
    q4Changed.add(soap, 8);
  },
  '数量は1以上10以下の整数で指定してください: 13'
);
checkThrows(
  '問題4: カートにない商品',
  () => {
    q4Changed.changeQuantity(3, 1);
  },
  'カートにない商品です: productId=3'
);

// 支払総額の内訳（解答の表に書いた数値）
checkNumber('問題4 手順1 小計', q4Changed.subtotal, 3390);
checkNumber('問題4 手順4 消費税', Math.floor(3390 * TAX_RATE), 339);
checkNumber('問題4 手順5 税込商品合計', 3390 + 339, 3729);
checkNumber('問題4 手順6 送料', calcShippingFee(3729), 0);

// fromItems は add を経由するので、復元時にも不変条件が効く
checkThrows(
  '問題4: 不正な保存データは復元時に弾く',
  () => {
    Cart.fromItems(1, [{ id: 1, userId: 1, productId: 1, quantity: 999 }], productById);
  },
  '数量は1以上10以下の整数で指定してください: 999'
);
// 商品が見つからない明細は捨てる
checkNumber(
  '問題4: 存在しない商品の明細は捨てる',
  Cart.fromItems(1, [{ id: 1, userId: 1, productId: 99, quantity: 1 }], productById).lineCount,
  0
);
checkBoolean('問題4: 空のカートは isEmpty', Cart.empty(1).isEmpty, true);
checkBoolean('問題4: 復元したカートは isEmpty ではない', q4Restored.isEmpty, false);
// 元のカートは変わらない（すべての操作が新しい Cart を返す）
checkNumber('問題4: 元のカートは変わらない', q4Restored.itemCount, 3);

// ---------------------------------------------------------------------------
// 問題5：抽象クラスと継承で割引を表す
// ---------------------------------------------------------------------------
function solveQ5(): string {
  const subtotal = 3790;
  const discounts: readonly Discount[] = [
    new PercentDiscount(10),
    new FixedAmountDiscount(500),
    new RankDiscount('gold'),
    new RankDiscount('none'),
    new CappedPercentDiscount(10, 300),
  ];

  const lines = discounts.map(
    (discount) => `${describeDiscount(discount)} → ${discount.amountFor(subtotal)}円引き`
  );

  lines.push(`小計200円に500円OFF → ${new FixedAmountDiscount(500).amountFor(200)}円引き`);

  const goldCart = Cart.empty(1).add(soap, 3).add(mug, 1);
  lines.push(
    `gold のお支払い金額: ${goldCart.summary(new RankDiscount('gold').toRule()).payableAmount}円`
  );

  return lines.join('\n');
}

checkString(
  '問題5: 出力7行',
  solveQ5(),
  '10%OFF（率: 10%） → 379円引き\n' +
    '500円OFF（固定額: 500円） → 500円引き\n' +
    '10%OFF（会員ランク: gold） → 379円引き\n' +
    '0%OFF（会員ランク: none） → 0円引き\n' +
    '10%OFF（上限: 300円） → 300円引き\n' +
    '小計200円に500円OFF → 200円引き\n' +
    'gold のお支払い金額: 3752円'
);

// 問題5 で作るカートは本文の merged と同じ小計になる
checkNumber('問題5: 石けん3点 + マグカップ1点の小計', Cart.empty(1).add(soap, 3).add(mug, 1).subtotal, 3790);
// クリップは親に1回だけ書かれている（サブクラスの rawAmount は素の値を返す）
checkNumber('問題5: 固定額は小計でクリップされる', new FixedAmountDiscount(500).amountFor(200), 200);
checkNumber('問題5: 率の割引はクリップされない', new PercentDiscount(10).amountFor(3790), 379);
checkNumber('問題5: 上限つきは上限で止まる', new CappedPercentDiscount(10, 300).amountFor(3790), 300);
checkNumber('問題5: 上限に届かなければそのまま', new CappedPercentDiscount(10, 300).amountFor(1000), 100);
checkString('問題5: RankDiscount のラベルは親が作る', new RankDiscount('silver').label, '5%OFF');

// ---------------------------------------------------------------------------
// 問題6：implements とコンポジション
// ---------------------------------------------------------------------------
function solveQ6(): string {
  const percent10 = new PercentDiscount(10);
  const combinedTwo = new CombinedDiscount([percent10, coupon]);
  const combinedThree = new CombinedDiscount([percent10, coupon, campaignPolicy]);

  const describe = (policy: DiscountPolicy, subtotal: number): string =>
    `${policy.label} → ${policy.amountFor(subtotal)}円引き`;

  const cart = Cart.empty(1).add(soap, 3).add(mug, 1); // 小計3790円
  const summary = cart.summary((subtotal) => combinedThree.amountFor(subtotal));
  const smallSummary = Cart.empty(1).add(soap, 2).summary(noDiscount); // 税込1056円

  return [
    describe(coupon, 3790),
    describe(campaignPolicy, 3790),
    describe(combinedTwo, 3790),
    describe(combinedThree, 3790),
    `小計100円に3つ適用 → ${combinedThree.amountFor(100)}円引き`,
    `3つ適用後のお支払い金額: ${summary.payableAmount}円`,
    `送料無料まであと${calcRemainingForFreeShipping(smallSummary.totalWithTax)}円（税込商品合計${smallSummary.totalWithTax}円のカート）`,
  ].join('\n');
}

checkString(
  '問題6: 出力7行',
  solveQ6(),
  'クーポン SPRING → 300円引き\n' +
    '春の全品100円OFF → 100円引き\n' +
    '10%OFF + クーポン SPRING → 679円引き\n' +
    '10%OFF + クーポン SPRING + 春の全品100円OFF → 779円引き\n' +
    '小計100円に3つ適用 → 100円引き\n' +
    '3つ適用後のお支払い金額: 3312円\n' +
    '送料無料まであと1944円（税込商品合計1056円のカート）'
);

// 合算後のクリップが無いと支払総額がマイナスになりうる（クリップを1か所に置く意味）
checkNumber('問題6: 合算は小計でクリップされる', 10 + 300 + 100, 410);
checkNumber(
  '問題6: クリップ後は小計と同額',
  new CombinedDiscount([new PercentDiscount(10), coupon, campaignPolicy]).amountFor(100),
  100
);
// 支払総額の内訳（解答に書いた数値）
checkNumber('問題6 手順3 割引後小計', 3790 - 779, 3011);
checkNumber('問題6 手順4 消費税', Math.floor(3011 * TAX_RATE), 301);
checkNumber('問題6 手順5 税込商品合計', 3011 + 301, 3312);
// Discount のサブクラスは DiscountPolicy としても通る（構造的部分型）
const policyFromClass: DiscountPolicy = new PercentDiscount(10);
checkNumber('問題6: Discount は DiscountPolicy を満たす', policyFromClass.amountFor(3790), 379);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session15: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session15: ok');
