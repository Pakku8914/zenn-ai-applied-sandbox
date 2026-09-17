/**
 * セッション11「型エイリアス・interface・ユニオン型」の検証スクリプト。
 *
 * 本文（037）と練習問題の解答（039）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * 章では複数のファイルに分けて書いているコードを、この1ファイルにまとめている。
 * そのため、章では同じ名前を使っている関数を一部だけ改名している
 * （本文1節の describeProduct と 問題1の describeProduct は書式が違うため、
 *   ここでは describeProductBody / describeProductQ1 としている）。
 *
 * 実行: docker compose exec ts npx tsx src/session11/verify.ts
 */

// ---------------------------------------------------------------------------
// 共通の定数（本書は金額を整数の円で扱う）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;

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

// ---------------------------------------------------------------------------
// この章で正式に定義した型（requirements.md の固定エンティティと一致させる）
// ---------------------------------------------------------------------------

/** 商品。price は税抜・整数の円 */
type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

/** 商品カテゴリ */
type Category = {
  id: number;
  name: string;
  slug: string;
};

/** 商品の登録票。id はまだ無い */
type ProductInput = {
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

/** 割引ルール：小計を受け取って割引額を返す */
type DiscountRule = (subtotal: number) => number;

/** 検索結果：商品が見つかったか、見つからなかったか */
type SearchResult = Product | undefined;

/** 画像URL。未設定の商品は null */
type ImageUrl = string | null;

/** 送料は0円か500円しかない */
type ShippingFee = 0 | 500;

/** 注文ステータス（4種類固定） */
type OrderStatus = 'pending' | 'paid' | 'shipped' | 'cancelled';

/** 会員ランク（4種類固定） */
type MemberRank = 'gold' | 'silver' | 'bronze' | 'none';

/** 作成日時・更新日時を持つことを表す型 */
type Timestamped = {
  createdAt: string;
  updatedAt: string;
};

/** 保存済みの商品（交差型） */
type StoredProduct = Product & Timestamped;

/** カートに入っている1件 */
type CartItem = {
  id: number;
  userId: number;
  productId: number;
  quantity: number;
};

/** 表示用の明細（交差型） */
type CartItemWithProduct = CartItem & { product: Product };

/** 支払いの内訳（セッション8で9行書いた型注釈に名前を付けたもの） */
type PaymentSummary = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

/** 本文2節：型エイリアスは別名にすぎない */
type Money = number;
type Quantity = number;

/** 注文ステータスの一覧（本文7節・問題5） */
const ORDER_STATUSES = ['pending', 'paid', 'shipped', 'cancelled'] as const;

// ---------------------------------------------------------------------------
// この章で使う共通データ（fixtures/products.json と同じ値）
// ---------------------------------------------------------------------------
const categories: Category[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const products: Product[] = [
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

// ---------------------------------------------------------------------------
// 章をまたいで使う関数（型に名前が付いたのでシグネチャが1行に収まる）
// ---------------------------------------------------------------------------

/** 本文1節の表示関数 */
const describeProductBody = (product: Product): string =>
  `${product.name}：${product.price}円（在庫${product.stock}点）`;

/** 問題1の表示関数（書式が本文と違う） */
const describeProductQ1 = (product: Product): string =>
  `${product.name}（${product.price}円 / 在庫${product.stock}点）`;

const describeCategory = (category: Category): string => `${category.name}（${category.slug}）`;

/** 在庫金額の合計 */
const sumStockValue = (items: Product[]): number =>
  items.reduce((total, item) => total + item.price * item.stock, 0);

/** 割引率（%）から割引ルールを作る高階関数（S06） */
const makePercentDiscount = (percent: number): DiscountRule => {
  return (subtotal: number): number => Math.floor((subtotal * percent) / 100);
};

/** 送料。判定基準は税込商品合計。戻り値は 0 か 500 のどちらか */
const calcShippingFee = (totalWithTax: number): ShippingFee =>
  totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;

/** 支払総額（計算手順の2〜7） */
const calcPayableAmount = (subtotal: number, rule: DiscountRule): number => {
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  return totalWithTax + calcShippingFee(totalWithTax); // 手順6・7
};

/** 登録票を受け取り、id を振って新しい配列を返す */
const addProduct = (items: Product[], input: ProductInput): Product[] => {
  const nextId = items.reduce((max, item) => (item.id > max ? item.id : max), 0) + 1;
  return [...items, { id: nextId, ...input }];
};

const findProductById = (items: Product[], id: number): SearchResult =>
  items.find((item) => item.id === id);

const describeSearch = (result: SearchResult): string => {
  if (result === undefined) {
    return '該当する商品がありません';
  }
  return `${result.name}：${result.price}円`;
};

const resolveImageUrl = (imageUrl: ImageUrl): string =>
  imageUrl ?? '/images/products/no-image.png';

/** ステータスの説明。ユニオン型なので default を書かなくてよい */
const describeOrderStatus = (status: OrderStatus): string => {
  switch (status) {
    case 'pending':
      return '支払い待ち';
    case 'paid':
      return '支払い済み';
    case 'shipped':
      return '発送済み';
    case 'cancelled':
      return 'キャンセル済み';
  }
};

/** 本文6節 Bad：引数が string だとスペルミスが default に落ちる */
const describeOrderStatusLoose = (status: string): string => {
  switch (status) {
    case 'pending':
      return '支払い待ち';
    case 'paid':
      return '支払い済み';
    default:
      return '不明なステータス';
  }
};

const canCancelOrder = (status: OrderStatus): boolean => {
  switch (status) {
    case 'pending':
    case 'paid':
      return true;
    case 'shipped':
    case 'cancelled':
      return false;
  }
};

const canTransitionTo = (current: OrderStatus, next: OrderStatus): boolean => {
  if (current === next) {
    return false;
  }
  switch (current) {
    case 'pending':
      return next === 'paid' || next === 'cancelled';
    case 'paid':
      return next === 'shipped' || next === 'cancelled';
    case 'shipped':
    case 'cancelled':
      return false;
  }
};

const resolveMemberRank = (totalSpent: number): MemberRank => {
  if (totalSpent >= 50000) {
    return 'gold';
  }
  if (totalSpent >= 20000) {
    return 'silver';
  }
  if (totalSpent >= 5000) {
    return 'bronze';
  }
  return 'none';
};

const discountPercentByRank = (rank: MemberRank): number => {
  switch (rank) {
    case 'gold':
      return 10;
    case 'silver':
      return 5;
    case 'bronze':
      return 3;
    case 'none':
      return 0;
  }
};

const withTimestamps = (product: Product, at: string): StoredProduct => ({
  ...product,
  createdAt: at,
  updatedAt: at,
});

const calcLineTotal = (price: number, quantity: number): number => price * quantity;

const calcSubtotal = (lines: CartItemWithProduct[]): number =>
  lines.reduce((total, line) => total + calcLineTotal(line.product.price, line.quantity), 0);

const buildProductById = (items: Product[]): Map<number, Product> => {
  const byId = new Map<number, Product>();
  for (const item of items) {
    byId.set(item.id, item);
  }
  return byId;
};

const buildCartLines = (items: CartItem[], byId: Map<number, Product>): CartItemWithProduct[] => {
  const lines: CartItemWithProduct[] = [];
  for (const item of items) {
    const product = byId.get(item.productId);
    if (product === undefined) {
      continue;
    }
    lines.push({ ...item, product });
  }
  return lines;
};

const buildPaymentSummary = (lines: CartItemWithProduct[], rule: DiscountRule): PaymentSummary => {
  const subtotal = calcSubtotal(lines); // 手順1
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  const shippingFee = calcShippingFee(totalWithTax); // 手順6
  const payableAmount = totalWithTax + shippingFee; // 手順7
  return {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount,
  };
};

// ---------------------------------------------------------------------------
// 本文 1節：type で型に名前を付ける
// ---------------------------------------------------------------------------
function bodyTypeAliasBasics(): string {
  const lines: string[] = [];
  for (const product of products) {
    lines.push(describeProductBody(product));
  }
  for (const category of categories) {
    lines.push(describeCategory(category));
  }
  return lines.join('\n');
}

checkString(
  '本文1節: 型に名前を付けて再利用する',
  bodyTypeAliasBasics(),
  'ラベンダーの石けん：480円（在庫24点）\n' +
    'ハンドクリーム：1800円（在庫12点）\n' +
    'マグカップ：2350円（在庫3点）\n' +
    'リネンのふきん：990円（在庫0点）\n' +
    'コットンのトートバッグ：2800円（在庫5点）\n' +
    'バス・ボディケア（bath-body）\n' +
    'キッチン雑貨（kitchen）\n' +
    'ファブリック（fabric）'
);

// Bad/Good（bad-inline-type.ts / good-type-alias.ts）はどちらも同じ結果になる
const bodyApplyRestock = (product: Product, amount: number): Product => ({
  ...product,
  stock: product.stock + amount,
});

function bodyRestockResult(): string {
  const mug = findProductById(products, 3);
  if (mug === undefined) {
    return '(マグカップが見つかりません)';
  }
  const restocked = bodyApplyRestock(mug, 10);
  return `${restocked.name}：在庫${restocked.stock}点 / 元の在庫${mug.stock}点`;
}

checkString('本文1節 Good: 引数と戻り値が同じ型', bodyRestockResult(), 'マグカップ：在庫13点 / 元の在庫3点');

// ---------------------------------------------------------------------------
// 本文 2節：型エイリアスは「別名」にすぎない
// ---------------------------------------------------------------------------
function bodyAliasIsNickname(): string {
  const price: Money = 480;
  const quantity: Quantity = 2;

  // 「金額」に「個数」を代入できてしまう（どちらも実体は number）
  const wrong: Money = quantity;
  checkNumber('本文2節: 別名どうしは代入できる', wrong, 2);

  return `${price} + ${quantity} = ${price + quantity}`;
}

checkString('本文2節: 型エイリアスは別名', bodyAliasIsNickname(), '480 + 2 = 482');

// 構造的部分型：Product と名乗っていないオブジェクトも、形が合えば渡せる（本文2節）
checkString(
  '本文2節: 形が合っていれば渡せる',
  describeProductBody({
    id: 99,
    name: 'サンプル',
    price: 100,
    stock: 1,
    description: '形が合っていれば通ります。',
    imageUrl: '/images/products/no-image.png',
    categoryId: 1,
  }),
  'サンプル：100円（在庫1点）'
);

// 関数型に名前を付ける（DiscountRule）
const bodyNoDiscount: DiscountRule = () => 0;

checkNumber('本文2節: 割引なしの支払総額', calcPayableAmount(5560, bodyNoDiscount), 6116);
checkNumber('本文2節: ブロンズ3%の支払総額', calcPayableAmount(5560, makePercentDiscount(3)), 5933);

// 本文に書いた内訳の検算
checkNumber('本文2節: 割引なしの消費税', Math.floor(5560 * TAX_RATE), 556);
checkNumber('本文2節: ブロンズの割引額', makePercentDiscount(3)(5560), 166);
checkNumber('本文2節: ブロンズの割引後小計', 5560 - 166, 5394);
checkNumber('本文2節: ブロンズの消費税', Math.floor(5394 * TAX_RATE), 539);

// ---------------------------------------------------------------------------
// 本文 3節：まだ id が無い型（ProductInput）
// ---------------------------------------------------------------------------
function bodyProductInput(): string {
  const bathSaltInput: ProductInput = {
    name: '入浴剤',
    price: 650,
    stock: 10,
    description: '炭酸ガスでゆっくり温まる入浴剤です。',
    imageUrl: '/images/products/no-image.png',
    categoryId: 1,
  };

  const lines: string[] = [];
  lines.push(
    `登録前: ${bathSaltInput.name}（${bathSaltInput.price}円 / 在庫${bathSaltInput.stock}点）`
  );

  const nextProducts = addProduct(products, bathSaltInput);
  const added = nextProducts.find((item) => item.name === '入浴剤');
  if (added !== undefined) {
    lines.push(`登録後: id=${added.id} ${added.name}`);
  }
  lines.push(`商品数: ${products.length}点 → ${nextProducts.length}点`);
  return lines.join('\n');
}

checkString(
  '本文3節: 登録票から商品を作る',
  bodyProductInput(),
  '登録前: 入浴剤（650円 / 在庫10点）\n登録後: id=6 入浴剤\n商品数: 5点 → 6点'
);

// ---------------------------------------------------------------------------
// 本文 5節：ユニオン型
// ---------------------------------------------------------------------------
function bodySearchResult(): string {
  return [
    describeSearch(findProductById(products, 3)),
    describeSearch(findProductById(products, 99)),
  ].join('\n');
}

checkString(
  '本文5節: Product | undefined',
  bodySearchResult(),
  'マグカップ：2350円\n該当する商品がありません'
);

function bodyUnionBasics(): string {
  return [
    resolveImageUrl('/images/products/lavender-soap.png'),
    resolveImageUrl(null),
    `2980円のとき: ${calcShippingFee(2980)}円`,
    `3000円のとき: ${calcShippingFee(3000)}円`,
  ].join('\n');
}

checkString(
  '本文5節: string | null と 0 | 500',
  bodyUnionBasics(),
  '/images/products/lavender-soap.png\n' +
    '/images/products/no-image.png\n' +
    '2980円のとき: 500円\n' +
    '3000円のとき: 0円'
);

// ---------------------------------------------------------------------------
// 本文 6節：リテラル型と as const
// ---------------------------------------------------------------------------
function bodyMemberRank(): string {
  const lines: string[] = [];
  for (const totalSpent of [60000, 30000, 8000, 1000]) {
    const rank = resolveMemberRank(totalSpent);
    lines.push(`${totalSpent}円 → ${rank}（${discountPercentByRank(rank)}%割引）`);
  }
  return lines.join('\n');
}

checkString(
  '本文6節: 会員ランクと割引率',
  bodyMemberRank(),
  '60000円 → gold（10%割引）\n' +
    '30000円 → silver（5%割引）\n' +
    '8000円 → bronze（3%割引）\n' +
    '1000円 → none（0%割引）'
);

// Bad：引数が string だとスペルミスが静かに default へ落ちる
checkString('本文6節 Bad: string 引数のスペルミス', describeOrderStatusLoose('payed'), '不明なステータス');

function bodyTransition(): string {
  const lines: string[] = [];
  for (const [from, to] of [
    ['pending', 'paid'],
    ['paid', 'shipped'],
    ['paid', 'paid'],
  ] as const) {
    lines.push(`${from} → ${to}: ${canTransitionTo(from, to)}`);
  }
  return lines.join('\n');
}

checkString(
  '本文6節: 状態遷移の判定',
  bodyTransition(),
  'pending → paid: true\npaid → shipped: true\npaid → paid: false'
);

// 本文から出力例を削った組み合わせも、ここで挙動を押さえておく
checkBoolean('本文6節: pending → shipped は不可', canTransitionTo('pending', 'shipped'), false);
checkBoolean('本文6節: shipped → cancelled は不可', canTransitionTo('shipped', 'cancelled'), false);

// ---------------------------------------------------------------------------
// 本文 7節：enum を使わず as const の配列 + リテラル型のユニオン
// ---------------------------------------------------------------------------
function bodyStatusList(): string {
  const lines: string[] = [];
  for (const s of ORDER_STATUSES) {
    lines.push(`${s}: ${describeOrderStatus(s)}`);
  }
  return lines.join('\n');
}

checkString(
  '本文7節: 一覧をループする',
  bodyStatusList(),
  'pending: 支払い待ち\npaid: 支払い済み\nshipped: 発送済み\ncancelled: キャンセル済み'
);

// 配列から作った型が、手で書いたユニオン型と同じものであることの確認
// （型が違えば describeOrderStatus に渡した時点で型エラーになる）
const derivedStatus: (typeof ORDER_STATUSES)[number] = 'shipped';
checkString('本文7節: 配列から作った型は同じ型', describeOrderStatus(derivedStatus), '発送済み');
checkNumber('本文7節: 一覧の件数', ORDER_STATUSES.length, 4);

// ---------------------------------------------------------------------------
// 本文 8節：交差型
// ---------------------------------------------------------------------------
function bodyIntersection(): string {
  const lines: string[] = [];
  for (const product of products.filter((item) => item.categoryId === 2)) {
    const stored = withTimestamps(product, '2026-08-27');
    lines.push(`${stored.name} / 登録日 ${stored.createdAt} / 更新日 ${stored.updatedAt}`);
  }
  return lines.join('\n');
}

checkString(
  '本文8節: Product & Timestamped',
  bodyIntersection(),
  'マグカップ / 登録日 2026-08-27 / 更新日 2026-08-27'
);

// ---------------------------------------------------------------------------
// 本文 8節（総合）：カートの明細と支払いの内訳
// ---------------------------------------------------------------------------
const bodyCartItems: CartItem[] = [
  { id: 1, userId: 1, productId: 1, quantity: 2 },
  { id: 2, userId: 1, productId: 2, quantity: 1 },
  { id: 3, userId: 1, productId: 5, quantity: 1 },
];

function bodyCartSummary(): string {
  const productById = buildProductById(products);
  const lines = buildCartLines(bodyCartItems, productById);

  const out: string[] = [];
  for (const line of lines) {
    const lineTotal = calcLineTotal(line.product.price, line.quantity);
    out.push(`${line.product.name} ${line.product.price}円 × ${line.quantity}点 = ${lineTotal}円`);
  }

  const rank: MemberRank = resolveMemberRank(8000);
  const summary = buildPaymentSummary(lines, makePercentDiscount(discountPercentByRank(rank)));

  out.push(`小計: ${summary.subtotal}円`);
  out.push(`割引額: ${summary.discountAmount}円`);
  out.push(`割引後小計: ${summary.discountedTotal}円`);
  out.push(`消費税: ${summary.tax}円`);
  out.push(`税込商品合計: ${summary.totalWithTax}円`);
  out.push(`送料: ${summary.shippingFee}円`);
  out.push(`お支払い金額: ${summary.payableAmount}円`);
  return out.join('\n');
}

checkString(
  '本文8節: カートの支払い内訳',
  bodyCartSummary(),
  'ラベンダーの石けん 480円 × 2点 = 960円\n' +
    'ハンドクリーム 1800円 × 1点 = 1800円\n' +
    'コットンのトートバッグ 2800円 × 1点 = 2800円\n' +
    '小計: 5560円\n' +
    '割引額: 166円\n' +
    '割引後小計: 5394円\n' +
    '消費税: 539円\n' +
    '税込商品合計: 5933円\n' +
    '送料: 0円\n' +
    'お支払い金額: 5933円'
);

// ---------------------------------------------------------------------------
// 問題1：商品とカテゴリに型の名前を付ける
// ---------------------------------------------------------------------------
function solveQ1(): string {
  const numberedLines = products.map(
    (product, index) => `${index + 1}. ${describeProductQ1(product)}`
  );

  const out: string[] = [...numberedLines];
  out.push(`カテゴリ: ${categories.map(describeCategory).join(' / ')}`);
  out.push(`在庫金額の合計: ${sumStockValue(products)}円`);
  return out.join('\n');
}

checkString(
  '問題1: 出力7行',
  solveQ1(),
  '1. ラベンダーの石けん（480円 / 在庫24点）\n' +
    '2. ハンドクリーム（1800円 / 在庫12点）\n' +
    '3. マグカップ（2350円 / 在庫3点）\n' +
    '4. リネンのふきん（990円 / 在庫0点）\n' +
    '5. コットンのトートバッグ（2800円 / 在庫5点）\n' +
    'カテゴリ: バス・ボディケア（bath-body） / キッチン雑貨（kitchen） / ファブリック（fabric）\n' +
    '在庫金額の合計: 54170円'
);

checkNumber('問題1: 在庫金額の合計', sumStockValue(products), 54170);

// ---------------------------------------------------------------------------
// 問題2：注文ステータスと会員ランクをリテラル型にする
// ---------------------------------------------------------------------------
function solveQ2(): string {
  const out: string[] = [];
  for (const status of ORDER_STATUSES) {
    out.push(
      `${status}: ${describeOrderStatus(status)} / キャンセル可: ${canCancelOrder(status)}`
    );
  }
  for (const totalSpent of [60000, 30000, 8000, 1000]) {
    const rank = resolveMemberRank(totalSpent);
    out.push(`${totalSpent}円 → ${rank}（${discountPercentByRank(rank)}%割引）`);
  }
  return out.join('\n');
}

checkString(
  '問題2: 出力8行',
  solveQ2(),
  'pending: 支払い待ち / キャンセル可: true\n' +
    'paid: 支払い済み / キャンセル可: true\n' +
    'shipped: 発送済み / キャンセル可: false\n' +
    'cancelled: キャンセル済み / キャンセル可: false\n' +
    '60000円 → gold（10%割引）\n' +
    '30000円 → silver（5%割引）\n' +
    '8000円 → bronze（3%割引）\n' +
    '1000円 → none（0%割引）'
);

// キャンセル可否の個別確認（解答②の裏付け）
checkBoolean('問題2: pending はキャンセル可', canCancelOrder('pending'), true);
checkBoolean('問題2: shipped はキャンセル不可', canCancelOrder('shipped'), false);

// しきい値の境界（解答④の裏付け）
checkString('問題2: 50000円ちょうどは gold', resolveMemberRank(50000), 'gold');
checkString('問題2: 49999円は silver', resolveMemberRank(49999), 'silver');
checkString('問題2: 4999円は none', resolveMemberRank(4999), 'none');

// ---------------------------------------------------------------------------
// 問題3：「無いかもしれない」をユニオン型で表す
// ---------------------------------------------------------------------------
function solveQ3(): string {
  return [
    `id=3: ${describeSearch(findProductById(products, 3))}`,
    `id=99: ${describeSearch(findProductById(products, 99))}`,
    `画像1: ${resolveImageUrl('/images/products/lavender-soap.png')}`,
    `画像2: ${resolveImageUrl(null)}`,
    `送料: 2980円→${calcShippingFee(2980)}円 / 3000円→${calcShippingFee(3000)}円`,
  ].join('\n');
}

checkString(
  '問題3: 出力5行',
  solveQ3(),
  'id=3: マグカップ：2350円\n' +
    'id=99: 該当する商品がありません\n' +
    '画像1: /images/products/lavender-soap.png\n' +
    '画像2: /images/products/no-image.png\n' +
    '送料: 2980円→500円 / 3000円→0円'
);

// 選択問題の裏付け：?? は null のときだけ既定値を使う（空文字列はそのまま）
checkString('問題3: ?? は空文字列を置き換えない', resolveImageUrl(''), '');

// ---------------------------------------------------------------------------
// 問題4：交差型でカートの明細を組み立てる
// ---------------------------------------------------------------------------
const q4CartItems: CartItem[] = [
  { id: 1, userId: 1, productId: 2, quantity: 1 },
  { id: 2, userId: 1, productId: 3, quantity: 2 },
  { id: 3, userId: 1, productId: 99, quantity: 1 }, // 存在しない商品
];

const q4SoapOnlyItems: CartItem[] = [{ id: 4, userId: 1, productId: 1, quantity: 2 }];

function solveQ4(): string {
  const productById = buildProductById(products);
  const lines = buildCartLines(q4CartItems, productById);

  const out: string[] = [];
  for (const line of lines) {
    const lineTotal = calcLineTotal(line.product.price, line.quantity);
    out.push(`${line.product.name} ${line.product.price}円 × ${line.quantity}点 = ${lineTotal}円`);
  }
  out.push(
    `明細${lines.length}件（見つからない商品を${q4CartItems.length - lines.length}件スキップしました）`
  );

  const rank: MemberRank = resolveMemberRank(30000);
  const summary = buildPaymentSummary(lines, makePercentDiscount(discountPercentByRank(rank)));

  out.push(`小計: ${summary.subtotal}円`);
  out.push(`割引額: ${summary.discountAmount}円`);
  out.push(`割引後小計: ${summary.discountedTotal}円`);
  out.push(`消費税: ${summary.tax}円`);
  out.push(`税込商品合計: ${summary.totalWithTax}円`);
  out.push(`送料: ${summary.shippingFee}円`);
  out.push(`お支払い金額: ${summary.payableAmount}円`);

  const soapLines = buildCartLines(q4SoapOnlyItems, productById);
  const soapSummary = buildPaymentSummary(
    soapLines,
    makePercentDiscount(discountPercentByRank(resolveMemberRank(1000)))
  );

  out.push('--- 送料がかかる例 ---');
  out.push(
    `小計: ${soapSummary.subtotal}円 / お支払い金額: ${soapSummary.payableAmount}円` +
      `（送料${soapSummary.shippingFee}円）`
  );
  return out.join('\n');
}

checkString(
  '問題4: 出力12行',
  solveQ4(),
  'ハンドクリーム 1800円 × 1点 = 1800円\n' +
    'マグカップ 2350円 × 2点 = 4700円\n' +
    '明細2件（見つからない商品を1件スキップしました）\n' +
    '小計: 6500円\n' +
    '割引額: 325円\n' +
    '割引後小計: 6175円\n' +
    '消費税: 617円\n' +
    '税込商品合計: 6792円\n' +
    '送料: 0円\n' +
    'お支払い金額: 6792円\n' +
    '--- 送料がかかる例 ---\n' +
    '小計: 960円 / お支払い金額: 1556円（送料500円）'
);

// 計算手順の1ステップずつの検算（解答⑤・⑥に書いた数値）
checkNumber('問題4 手順1 小計', 1800 * 1 + 2350 * 2, 6500);
checkNumber('問題4 手順2 割引額（5%）', makePercentDiscount(5)(6500), 325);
checkNumber('問題4 手順3 割引後小計', 6500 - 325, 6175);
checkNumber('問題4 手順4 消費税', Math.floor(6175 * TAX_RATE), 617);
checkNumber('問題4 手順5 税込商品合計', 6175 + 617, 6792);
checkNumber('問題4 手順6 送料', calcShippingFee(6792), 0);
checkNumber('問題4 2件目 消費税', Math.floor(960 * TAX_RATE), 96);
checkNumber('問題4 2件目 送料', calcShippingFee(1056), 500);
checkNumber('問題4 2件目 支払総額', 1056 + 500, 1556);

// 問題4 別解：reduce で明細を組み立てる（結果は模範解答と同じ）
function solveQ4Alternative(): string {
  const byId = buildProductById(products);

  const buildCartLinesByReduce = (items: CartItem[], map: Map<number, Product>): CartItemWithProduct[] =>
    items.reduce<CartItemWithProduct[]>((lines, item) => {
      const product = map.get(item.productId);
      return product === undefined ? lines : [...lines, { ...item, product }];
    }, []);

  return buildCartLinesByReduce(q4CartItems, byId)
    .map((line) => `${line.product.name} × ${line.quantity}点`)
    .join(' / ');
}

checkString(
  '問題4 別解: reduce で明細を組み立てる',
  solveQ4Alternative(),
  'ハンドクリーム × 1点 / マグカップ × 2点'
);

// ---------------------------------------------------------------------------
// 問題5：as const の一覧からステータス遷移表を作る
// ---------------------------------------------------------------------------
const COLUMN_WIDTH = 11;

const buildTransitionTable = (statuses: readonly OrderStatus[]): string => {
  const header = ['from/to'.padEnd(COLUMN_WIDTH), ...statuses.map((s) => s.padEnd(COLUMN_WIDTH))]
    .join('')
    .trimEnd();

  const rows = statuses.map((from) =>
    [
      from.padEnd(COLUMN_WIDTH),
      ...statuses.map((to) => (canTransitionTo(from, to) ? 'OK' : '-').padEnd(COLUMN_WIDTH)),
    ]
      .join('')
      .trimEnd()
  );

  return [header, ...rows].join('\n');
};

const countTransitions = (statuses: readonly OrderStatus[]): number =>
  statuses.reduce(
    (count, from) => count + statuses.filter((to) => canTransitionTo(from, to)).length,
    0
  );

function solveQ5(): string {
  return [
    `ステータス一覧（${ORDER_STATUSES.length}件）: ${ORDER_STATUSES.join(' / ')}`,
    buildTransitionTable(ORDER_STATUSES),
    `遷移できる組み合わせ: ${countTransitions(ORDER_STATUSES)}通り`,
  ].join('\n');
}

checkString(
  '問題5: 出力7行',
  solveQ5(),
  'ステータス一覧（4件）: pending / paid / shipped / cancelled\n' +
    'from/to    pending    paid       shipped    cancelled\n' +
    'pending    -          OK         -          OK\n' +
    'paid       -          -          OK         OK\n' +
    'shipped    -          -          -          -\n' +
    'cancelled  -          -          -          -\n' +
    '遷移できる組み合わせ: 4通り'
);

checkNumber('問題5: 遷移できる組み合わせの数', countTransitions(ORDER_STATUSES), 4);
checkBoolean('問題5: 同じステータスへは移れない', canTransitionTo('pending', 'pending'), false);
checkBoolean('問題5: shipped は終着点', canTransitionTo('shipped', 'cancelled'), false);

// ---------------------------------------------------------------------------
// 問題6：interface と type を比べる
// ---------------------------------------------------------------------------
// 章では type Product と同じ名前を使えないため、ここでは別名にしている
interface ProductByInterface {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
}

/** interface の extends（型エイリアスも継承元にできる） */
interface StoredProductByInterface extends ProductByInterface, Timestamped {}

/** 交差型による合成 */
type StoredProductByIntersection = ProductByInterface & Timestamped;

const withTimestampsByInterface = (
  product: ProductByInterface,
  at: string
): StoredProductByInterface => ({
  ...product,
  createdAt: at,
  updatedAt: at,
});

function solveQ6(): string {
  const mug = products.find((item) => item.id === 3);

  if (mug === undefined) {
    return 'マグカップが見つかりません';
  }

  const storedA: StoredProductByInterface = withTimestampsByInterface(mug, '2026-08-27');
  // interface 版 → 交差型版、交差型版 → interface 版 のどちらの向きにも代入できる
  const storedB: StoredProductByIntersection = storedA;
  const storedC: StoredProductByInterface = storedB;

  return [
    `[interface版] ${storedA.name} / 登録日 ${storedA.createdAt}`,
    `[交差型版] ${storedB.name} / 登録日 ${storedB.createdAt}`,
    `2つの型は相互に代入できる: ${storedC.name === storedA.name}`,
  ].join('\n');
}

checkString(
  '問題6: 出力3行',
  solveQ6(),
  '[interface版] マグカップ / 登録日 2026-08-27\n' +
    '[交差型版] マグカップ / 登録日 2026-08-27\n' +
    '2つの型は相互に代入できる: true'
);

// 交差型は9フィールドすべてを持つ（本文8節の説明の裏付け）
const q6Stored: StoredProduct = withTimestamps(
  {
    id: 3,
    name: 'マグカップ',
    price: 2350,
    stock: 3,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
    imageUrl: '/images/products/mug.png',
    categoryId: 2,
  },
  '2026-08-27'
);
checkNumber('問題6: 交差型のフィールド数', Object.keys(q6Stored).length, 9);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session11: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session11: ok');
