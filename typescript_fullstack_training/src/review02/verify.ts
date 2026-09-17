/**
 * 復習02「セッション11〜15の横断復習」の練習問題の解答を検証する。
 * 章に載せた「期待される出力」と1文字でも違えばエラー終了する。
 *
 * 型レベルの主張は次の2つの形でこのファイル自体に埋め込んでいる。
 *   - const _check: 期待する型 = 値;   … その型に代入できることを tsc に確認させる
 *   - @ts-expect-error                 … 次の1行が型エラーになることを tsc に確認させる
 * どちらも tsc --noEmit が通らなければ失敗する（verify-all.sh は先に型チェックを実行する）。
 *
 * 実行: docker compose exec ts npx tsx src/review02/verify.ts
 */

/** 比較できる値 */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}`);
    console.error(`  期待値: ${String(expected)}`);
    console.error(`  実際　: ${String(actual)}`);
    process.exit(1);
  }
};

// ---------------------------------------------------------------------------
// 共通の前提コード（練習問題章の「共通の前提コード」と同じ）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;
const MAX_CART_QUANTITY = 10;

type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};
type Category = { id: number; name: string; slug: string };
type CartItem = { id: number; userId: number; productId: number; quantity: number };
type CartLine = { product: Product; quantity: number };
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
type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

const CATEGORIES: readonly Category[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const PRODUCTS: readonly Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1,
    description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
    imageUrl: '/images/products/lavender-soap.png' },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png' },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
    imageUrl: '/images/products/mug.png' },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3,
    description: '洗うほどやわらかくなるリネン100%のふきんです。',
    imageUrl: '/images/products/linen-cloth.png' },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3,
    description: 'A4サイズが入る、しっかりした厚手のトートバッグです。',
    imageUrl: '/images/products/tote-bag.png' },
];

function requireProduct(id: number): Product {
  const found = PRODUCTS.find((product) => product.id === id);
  if (found === undefined) {
    throw new Error(`商品マスタが壊れています: id=${id}`);
  }
  return found;
}

function calcSubtotal<T extends { price: number; quantity: number }>(lines: readonly T[]): number {
  return lines.reduce((total, line) => total + line.price * line.quantity, 0);
}

function calcCartSubtotal(lines: readonly CartLine[]): number {
  return calcSubtotal(lines.map((line) => ({ price: line.product.price, quantity: line.quantity })));
}

function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

function makePercentDiscount(percent: number): DiscountRule {
  return (subtotal: number): number => Math.floor((subtotal * percent) / 100);
}

function resolveMemberRank(totalSpent: number): MemberRank {
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
}

/** ランクごとの割引率（%）。Record なのでランクの追加漏れはコンパイルエラーになる */
const DISCOUNT_PERCENT_BY_RANK: Record<MemberRank, number> = {
  gold: 10,
  silver: 5,
  bronze: 3,
  none: 0,
};

function discountPercentByRank(rank: MemberRank): number {
  return DISCOUNT_PERCENT_BY_RANK[rank];
}

function buildPaymentSummary(lines: readonly CartLine[], rule: DiscountRule): PaymentSummary {
  const subtotal = calcCartSubtotal(lines);
  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);
  const payableAmount = totalWithTax + shippingFee;
  return { subtotal, discountAmount, discountedTotal, tax, totalWithTax, shippingFee, payableAmount };
}

// 共通の前提コードの前提を確認する
check('共通: マスタは5件', PRODUCTS.length, 5);
check('共通: 在庫切れの商品がある', requireProduct(4).stock, 0);
check('共通: 上限は10点', MAX_CART_QUANTITY, 10);
check('共通: ランク境界（21000円）', resolveMemberRank(21000), 'silver');
check('共通: ランク境界（1000円）', resolveMemberRank(1000), 'none');
check('共通: 送料は税込商品合計で判定（2999円）', calcShippingFee(2999), 500);
check('共通: 送料は税込商品合計で判定（3000円）', calcShippingFee(3000), 0);

// ---------------------------------------------------------------------------
// 問題2で導出した一覧と型（この1ファイルでは1回だけ定義する）
// ---------------------------------------------------------------------------
const ORDER_STATUSES = ['pending', 'paid', 'shipped', 'cancelled'] as const;
type OrderStatus = (typeof ORDER_STATUSES)[number];

// 一覧から導出した型が、セッション11で手書きしたユニオン型と同じ集合であること
const _statusFromArray: OrderStatus = 'cancelled';
const _statusHandWritten: 'pending' | 'paid' | 'shipped' | 'cancelled' = _statusFromArray;
const _statusBackToArray: OrderStatus = _statusHandWritten;
check('問題2: 導出した型と手書きの型は同じ', _statusBackToArray, 'cancelled');

// ---------------------------------------------------------------------------
// 問題1：注文の型から「ありえない状態」を消す（S11・S12・S08・S10）
// ---------------------------------------------------------------------------
type OrderBase = { id: number; userId: number; totalAmount: number; createdAt: string };

type PendingOrder = OrderBase & { kind: 'pending' };
type PaidOrder = OrderBase & { kind: 'paid'; paidAt: string };
type ShippedOrder = OrderBase & { kind: 'shipped'; paidAt: string; shippedAt: string };
type CancelledOrder = OrderBase & { kind: 'cancelled'; cancelledAt: string; reason: string };
type Order = PendingOrder | PaidOrder | ShippedOrder | CancelledOrder;

function describeOrder(order: Order): string {
  switch (order.kind) {
    case 'pending':
      return `#${order.id} お支払いをお待ちしています（${order.totalAmount}円）`;
    case 'paid':
      return `#${order.id} お支払いを確認しました（入金 ${order.paidAt}）`;
    case 'shipped':
      return `#${order.id} 発送済みです（入金 ${order.paidAt} / 出荷 ${order.shippedAt}）`;
    case 'cancelled':
      return `#${order.id} キャンセルされました（理由: ${order.reason}）`;
    default: {
      const _exhaustive: never = order;
      throw new Error(`未知の注文状態です: ${JSON.stringify(_exhaustive)}`);
    }
  }
}

function orderStatusOf(order: Order): OrderStatus {
  return order.kind;
}

const Q1_ORDERS: readonly Order[] = [
  { kind: 'pending', id: 1001, userId: 1, totalAmount: 1556, createdAt: '2026-08-20' },
  { kind: 'paid', id: 1002, userId: 1, totalAmount: 5933, createdAt: '2026-08-20',
    paidAt: '2026-08-21' },
  { kind: 'shipped', id: 1003, userId: 2, totalAmount: 6792, createdAt: '2026-08-19',
    paidAt: '2026-08-21', shippedAt: '2026-08-22' },
  { kind: 'cancelled', id: 1004, userId: 2, totalAmount: 3641, createdAt: '2026-08-18',
    cancelledAt: '2026-08-19', reason: '在庫切れのため' },
];

const q1Pending: PendingOrder = { kind: 'pending', id: 1001, userId: 1, totalAmount: 1556, createdAt: '2026-08-20' };

// タグの値はそのまま OrderStatus として使える
const _q1Status: OrderStatus = orderStatusOf(q1Pending);
check('問題1: タグは保存する値に使える', _q1Status, 'pending');

// shipped の注文は paidAt と shippedAt を必ず持つので、欠けていると代入できない
// @ts-expect-error 必須フィールドが欠けている
const q1Invalid: Order = { kind: 'shipped', id: 9999, userId: 1, totalAmount: 1, createdAt: 'x' };
check('問題1: 欠けたフィールドは型エラーになる', q1Invalid.kind, 'shipped');

// kind を確かめる前に shippedAt は読めない（TS2339）
// @ts-expect-error 絞り込む前のプロパティアクセス
const q1PeekShippedAt = (order: Order): string | undefined => order.shippedAt;
check('問題1: 絞り込まずに読むと実行時は undefined', String(q1PeekShippedAt(q1Pending)), 'undefined');

const q1Lines = [
  ...Q1_ORDERS.map((order) => describeOrder(order)),
  `DBに保存する status: ${Q1_ORDERS.map(orderStatusOf).join(' / ')}`,
  `4件の合計金額: ${Q1_ORDERS.reduce((total, order) => total + order.totalAmount, 0)}円`,
];

check(
  '問題1の出力',
  q1Lines.join('\n'),
  [
    '#1001 お支払いをお待ちしています（1556円）',
    '#1002 お支払いを確認しました（入金 2026-08-21）',
    '#1003 発送済みです（入金 2026-08-21 / 出荷 2026-08-22）',
    '#1004 キャンセルされました（理由: 在庫切れのため）',
    'DBに保存する status: pending / paid / shipped / cancelled',
    '4件の合計金額: 17922円',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題2：ステータスを増やしたときに直す場所をコンパイラに教えてもらう
// （S12・S14・S11・S08・S10）
// ---------------------------------------------------------------------------
const LOOSE_LABELS: { [key: string]: string } = {
  pending: '支払い待ち',
  paid: '支払い済み',
  shipped: '発送済み',
  cancelled: 'キャンセル済み',
};
const looseLabelOf = (status: string): string => LOOSE_LABELS[status] ?? '不明なステータス';

// インデックスシグネチャからの読み取りは undefined を含む
const _q2Loose: string | undefined = LOOSE_LABELS['paid'];
check('問題2: 緩い実装でも既存のキーは引ける', _q2Loose ?? '', '支払い済み');

const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  pending: '支払い待ち',
  paid: '支払い済み',
  shipped: '発送済み',
  cancelled: 'キャンセル済み',
};

// Record<有限のユニオン, V> の読み取りは undefined を含まない
const _q2Label: string = ORDER_STATUS_LABELS.paid;
check('問題2: Record の読み取りは string に確定する', _q2Label, '支払い済み');

const NEXT_STATUSES: Record<OrderStatus, readonly OrderStatus[]> = {
  pending: ['paid', 'cancelled'],
  paid: ['shipped', 'cancelled'],
  shipped: [],
  cancelled: [],
};

function canCancelOrder(status: OrderStatus): boolean {
  switch (status) {
    case 'pending':
    case 'paid':
      return true;
    case 'shipped':
    case 'cancelled':
      return false;
    default: {
      const _exhaustive: never = status;
      throw new Error(`未知の注文ステータスです: ${String(_exhaustive)}`);
    }
  }
}

function formatStatusRow(status: OrderStatus): string {
  const next = NEXT_STATUSES[status];
  const nextText = next.length === 0 ? '(なし)' : next.join(', ');
  return (
    `${status}: ${ORDER_STATUS_LABELS[status]} / ` +
    `キャンセル可: ${canCancelOrder(status)} / 次に進める: ${nextText}`
  );
}

// ステータスを1つ増やしたときに壊れる場所（解説の表の裏付け）
type Q2ExtendedStatus = OrderStatus | 'refunded';
// @ts-expect-error refunded のラベルが無いので Record を満たさない
const q2IncompleteLabels: Record<Q2ExtendedStatus, string> = { pending: '支払い待ち', paid: '支払い済み', shipped: '発送済み', cancelled: 'キャンセル済み' };
check('問題2: 抜けのある Record は型エラー', Object.keys(q2IncompleteLabels).length, 4);

// @ts-expect-error 'refunded' は OrderStatus に含まれない
const q2UnknownStatus: OrderStatus = 'refunded';
check('問題2: 一覧に無い値は代入できない', q2UnknownStatus, 'refunded');

check('問題2: キャンセル可（pending）', canCancelOrder('pending'), true);
check('問題2: キャンセル不可（shipped）', canCancelOrder('shipped'), false);

const q2Lines = [
  `[緩い実装] pending → ${looseLabelOf('pending')} / payed → ${looseLabelOf('payed')} / ` +
    `refunded → ${looseLabelOf('refunded')}`,
  ...ORDER_STATUSES.map((status) => formatStatusRow(status)),
  `一覧の件数: ${ORDER_STATUSES.length} / ` +
    `ラベルのキー数: ${Object.keys(ORDER_STATUS_LABELS).length} / ` +
    `遷移表のキー数: ${Object.keys(NEXT_STATUSES).length}`,
];

check(
  '問題2の出力',
  q2Lines.join('\n'),
  [
    '[緩い実装] pending → 支払い待ち / payed → 不明なステータス / refunded → 不明なステータス',
    'pending: 支払い待ち / キャンセル可: true / 次に進める: paid, cancelled',
    'paid: 支払い済み / キャンセル可: true / 次に進める: shipped, cancelled',
    'shipped: 発送済み / キャンセル可: false / 次に進める: (なし)',
    'cancelled: キャンセル済み / キャンセル可: false / 次に進める: (なし)',
    '一覧の件数: 4 / ラベルのキー数: 4 / 遷移表のキー数: 4',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題3：手書きの型定義を Product から導出する（S14・S13・S09・S08・S10）
// ---------------------------------------------------------------------------
type ProductInput = Omit<Product, 'id'>;
type ProductSummary = Pick<Product, 'id' | 'name' | 'price'>;
type ProductPatch = { id: number } & Partial<ProductInput>;

const PRODUCT_FIELD_LABELS: Record<keyof Product, string> = {
  id: '商品ID',
  name: '商品名',
  price: '価格',
  stock: '在庫',
  description: '説明',
  imageUrl: '画像パス',
  categoryId: 'カテゴリID',
};

function pick<T, K extends keyof T>(item: T, key: K): T[K] {
  return item[key];
}

function formatField<K extends keyof Product>(product: Product, key: K): string {
  return `${PRODUCT_FIELD_LABELS[key]}: ${String(pick(product, key))}`;
}

function formatSummary(summary: ProductSummary): string {
  return `#${summary.id} ${summary.name} ${summary.price}円`;
}

function toSummary(product: Product): ProductSummary {
  return { id: product.id, name: product.name, price: product.price };
}

type PaymentBreakdown = ReturnType<typeof buildPaymentSummary>;

function applyPatch(products: readonly Product[], patch: ProductPatch): Result<Product[], string> {
  const target = products.find((product) => product.id === patch.id);
  if (target === undefined) {
    return { kind: 'error', error: `商品が見つかりません: id=${patch.id}` };
  }
  const changedKeys = Object.keys(patch).filter((key) => key !== 'id');
  if (changedKeys.length === 0) {
    return { kind: 'error', error: '更新する項目がありません' };
  }
  return {
    kind: 'ok',
    value: products.map((product) =>
      product.id === patch.id ? { ...product, ...patch } : product
    ),
  };
}

const q3Mug = requireProduct(3);

// 導出した型が期待どおりの形であること
const _q3Input: ProductInput = {
  name: q3Mug.name,
  price: q3Mug.price,
  stock: q3Mug.stock,
  description: q3Mug.description,
  imageUrl: q3Mug.imageUrl,
  categoryId: q3Mug.categoryId,
};
check('問題3: Omit で作った登録票に id は無い', Object.keys(_q3Input).length, 6);

const _q3Price: Product['price'] = pick(q3Mug, 'price');
check('問題3: インデックスアクセス型', _q3Price, 2350);

// @ts-expect-error ProductSummary に stock は含まれない（余剰プロパティチェック）
const q3WrongSummary: ProductSummary = { id: 3, name: 'マグカップ', price: 2350, stock: 3 };
check('問題3: 選んでいない項目は渡せない', q3WrongSummary.id, 3);

// @ts-expect-error keyof Product に無いキーは渡せない
const q3WrongField = formatField(q3Mug, 'nmae');
check('問題3: タイポは型エラー（実行時は undefined）', q3WrongField, 'undefined: undefined');

const q3Raised = applyPatch(PRODUCTS, { id: 3, price: 2500 });
const q3Updated = q3Raised.kind === 'ok' ? q3Raised.value.find((p) => p.id === 3) : undefined;
const q3Empty = applyPatch(PRODUCTS, { id: 3 });
const q3Missing = applyPatch(PRODUCTS, { id: 99, price: 100 });
const q3Breakdown: PaymentBreakdown = buildPaymentSummary(
  [{ product: q3Mug, quantity: 1 }],
  makePercentDiscount(0)
);
const q3FieldKeys = Object.keys(PRODUCT_FIELD_LABELS);

check('問題3: 更新は成功する', q3Raised.kind, 'ok');
check('問題3: 元のマスタは無傷', requireProduct(3).price, 2350);
check('問題3: 空の更新は失敗する', q3Empty.kind, 'error');
check('問題3: 存在しない商品は失敗する', q3Missing.kind, 'error');
check('問題3: 更新後の配列は別物', q3Raised.kind === 'ok' ? q3Raised.value === PRODUCTS : true, false);

const q3Lines = [
  `商品の項目数: ${q3FieldKeys.length} / ` +
    `登録票（id を除く）の項目数: ${q3FieldKeys.filter((key) => key !== 'id').length}`,
  [formatField(q3Mug, 'price'), formatField(q3Mug, 'stock'), formatField(q3Mug, 'categoryId')].join(
    ' / '
  ),
  `サマリー: ${formatSummary(toSummary(q3Mug))}`,
  `値上げ: ${q3Mug.name} ${q3Mug.price}円 → ${q3Updated === undefined ? '?' : q3Updated.price}円` +
    `（元の配列は ${requireProduct(3).price}円 のまま）`,
  `空の更新: ${q3Empty.kind === 'error' ? q3Empty.error : '成功'}`,
  `存在しない商品: ${q3Missing.kind === 'error' ? q3Missing.error : '成功'}`,
  `支払い内訳の項目数（ReturnType で取り出した型）: ${Object.keys(q3Breakdown).length}`,
];

check(
  '問題3の出力',
  q3Lines.join('\n'),
  [
    '商品の項目数: 7 / 登録票（id を除く）の項目数: 6',
    '価格: 2350 / 在庫: 3 / カテゴリID: 2',
    'サマリー: #3 マグカップ 2350円',
    '値上げ: マグカップ 2350円 → 2500円（元の配列は 2350円 のまま）',
    '空の更新: 更新する項目がありません',
    '存在しない商品: 商品が見つかりません: id=99',
    '支払い内訳の項目数（ReturnType で取り出した型）: 7',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題4：同じ処理を3回書いているコードをジェネリクスでまとめる（S13・S10・S08）
// ---------------------------------------------------------------------------
function findById<T extends { id: number }>(items: readonly T[], id: number): T | undefined {
  return items.find((item) => item.id === id);
}

function buildIndex<T, K>(items: readonly T[], getKey: (item: T) => K): Map<K, T> {
  const index = new Map<K, T>();
  for (const item of items) {
    index.set(getKey(item), item);
  }
  return index;
}

function groupBy<T, K>(items: readonly T[], getKey: (item: T) => K): Map<K, T[]> {
  const groups = new Map<K, T[]>();
  for (const item of items) {
    const key = getKey(item);
    const current = groups.get(key) ?? [];
    groups.set(key, [...current, item]);
  }
  return groups;
}

function sumBy<T>(items: readonly T[], select: (item: T) => number): number {
  return items.reduce((total, item) => total + select(item), 0);
}

const Q4_CART_ITEMS: readonly CartItem[] = [
  { id: 1, userId: 1, productId: 1, quantity: 2 },
  { id: 2, userId: 1, productId: 3, quantity: 1 },
];

// 制約付きジェネリクスは T をそのまま運ぶ（Product のまま返る）
const _q4Found: Product | undefined = findById(PRODUCTS, 3);
const _q4Category: Category | undefined = findById(CATEGORIES, 2);
const _q4Index: Map<number, Product> = buildIndex(PRODUCTS, (product) => product.id);
const _q4BySlug: Map<string, Category> = buildIndex(CATEGORIES, (category) => category.slug);
check('問題4: 型引数が保たれる', _q4Found === undefined ? '' : _q4Found.name, 'マグカップ');
check('問題4: カテゴリも同じ関数で引ける', _q4Category === undefined ? '' : _q4Category.slug, 'kitchen');
check('問題4: 索引のキーは number', _q4Index.size, 5);
check('問題4: 索引のキーは string', _q4BySlug.size, 3);

// @ts-expect-error id を持たない値は findById に渡せない
const q4Rejected = findById([{ slug: 'bath-body' }], 1);
check('問題4: 制約を満たさない値は渡せない', q4Rejected === undefined, true);

const q4FoundProduct = findById(PRODUCTS, 3);
const q4NotFound = findById(PRODUCTS, 99);
const q4FoundCategory = findById(CATEGORIES, 2);
const q4FoundCartItem = findById(Q4_CART_ITEMS, 2);
const q4ProductById = buildIndex(PRODUCTS, (product) => product.id);
const q4CategoryBySlug = buildIndex(CATEGORIES, (category) => category.slug);
const q4Fabric = q4CategoryBySlug.get('fabric');
const q4ProductsByCategoryId = groupBy(PRODUCTS, (product) => product.categoryId);
const q4Summaries = CATEGORIES.map((category) => {
  const items = q4ProductsByCategoryId.get(category.id) ?? [];
  return {
    name: category.name,
    count: items.length,
    stockValue: sumBy(items, (item) => item.price * item.stock),
  };
});
const q4Top = q4Summaries.toSorted((a, b) => b.stockValue - a.stockValue).at(0);

check('問題4: グループ数', q4ProductsByCategoryId.size, 3);
check('問題4: バス・ボディケアの在庫金額', 480 * 24 + 1800 * 12, 33120);
check('問題4: キッチン雑貨の在庫金額', 2350 * 3, 7050);
check('問題4: ファブリックの在庫金額', 990 * 0 + 2800 * 5, 14000);
check('問題4: 全体の在庫金額', sumBy(PRODUCTS, (p) => p.price * p.stock), 54170);
check('問題4: toSorted は元の配列を壊さない', q4Summaries[0]?.name ?? '', 'バス・ボディケア');

const q4Lines = [
  `商品 id=3: ${q4FoundProduct === undefined ? '該当なし' : q4FoundProduct.name} / ` +
    `id=99: ${q4NotFound === undefined ? '該当なし' : q4NotFound.name}`,
  `カテゴリ id=2: ${
    q4FoundCategory === undefined ? '該当なし' : `${q4FoundCategory.name}（${q4FoundCategory.slug}）`
  } / カート明細 id=2: ${
    q4FoundCartItem === undefined
      ? '該当なし'
      : `productId=${q4FoundCartItem.productId} × ${q4FoundCartItem.quantity}点`
  }`,
  `索引: 商品${q4ProductById.size}件 / カテゴリ${q4CategoryBySlug.size}件 / ` +
    `slug=fabric → ${q4Fabric === undefined ? '(なし)' : q4Fabric.name}`,
  ...q4Summaries.map(
    (summary) => `${summary.name}: ${summary.count}件 / 在庫金額 ${summary.stockValue}円`
  ),
  `在庫金額が最大: ${q4Top === undefined ? 'なし' : `${q4Top.name}（${q4Top.stockValue}円）`} / ` +
    `全体 ${sumBy(PRODUCTS, (product) => product.price * product.stock)}円`,
];

check(
  '問題4の出力',
  q4Lines.join('\n'),
  [
    '商品 id=3: マグカップ / id=99: 該当なし',
    'カテゴリ id=2: キッチン雑貨（kitchen） / カート明細 id=2: productId=3 × 1点',
    '索引: 商品5件 / カテゴリ3件 / slug=fabric → ファブリック',
    'バス・ボディケア: 2件 / 在庫金額 33120円',
    'キッチン雑貨: 1件 / 在庫金額 7050円',
    'ファブリック: 2件 / 在庫金額 14000円',
    '在庫金額が最大: バス・ボディケア（33120円） / 全体 54170円',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題5：カート投入の失敗を Result と判別可能なユニオンで表す
// （S13・S12・S09・S10・S03）
// ---------------------------------------------------------------------------
type CartError =
  | { kind: 'invalid_quantity'; requested: number }
  | { kind: 'exceeds_max'; requested: number; max: number }
  | { kind: 'out_of_stock'; product: Product }
  | { kind: 'insufficient_stock'; product: Product; requested: number };

function formatCartError(error: CartError): string {
  switch (error.kind) {
    case 'invalid_quantity':
      return `数量は1以上の整数で指定してください（指定: ${error.requested}）`;
    case 'exceeds_max':
      return `1商品あたり${error.max}点までです（指定: ${error.requested}）`;
    case 'out_of_stock':
      return `${error.product.name} は在庫切れです`;
    case 'insufficient_stock':
      return (
        `${error.product.name} の在庫が足りません` +
        `（在庫${error.product.stock}点 / 希望${error.requested}点）`
      );
    default: {
      const _exhaustive: never = error;
      throw new Error(`未知のカートエラーです: ${JSON.stringify(_exhaustive)}`);
    }
  }
}

function addToCart(
  lines: readonly CartLine[],
  product: Product,
  quantity: number
): Result<CartLine[], CartError> {
  if (!Number.isInteger(quantity) || quantity < 1) {
    return { kind: 'error', error: { kind: 'invalid_quantity', requested: quantity } };
  }

  const current = lines.find((line) => line.product.id === product.id);
  const currentQuantity = current === undefined ? 0 : current.quantity;
  const requested = currentQuantity + quantity;

  if (requested > MAX_CART_QUANTITY) {
    return { kind: 'error', error: { kind: 'exceeds_max', requested, max: MAX_CART_QUANTITY } };
  }
  if (product.stock === 0) {
    return { kind: 'error', error: { kind: 'out_of_stock', product } };
  }
  if (product.stock < requested) {
    return { kind: 'error', error: { kind: 'insufficient_stock', product, requested } };
  }
  if (current === undefined) {
    return { kind: 'ok', value: [...lines, { product, quantity }] };
  }
  return {
    kind: 'ok',
    value: lines.map((line) =>
      line.product.id === product.id ? { ...line, quantity: requested } : line
    ),
  };
}

const _q5Result: Result<CartLine[], CartError> = addToCart([], requireProduct(3), 1);
check('問題5: 戻り値は Result', _q5Result.kind, 'ok');

// エラーの文言（4種類すべて）
check(
  '問題5: invalid_quantity の文言',
  formatCartError({ kind: 'invalid_quantity', requested: 0 }),
  '数量は1以上の整数で指定してください（指定: 0）'
);
check(
  '問題5: exceeds_max の文言',
  formatCartError({ kind: 'exceeds_max', requested: 11, max: MAX_CART_QUANTITY }),
  '1商品あたり10点までです（指定: 11）'
);
check(
  '問題5: out_of_stock の文言',
  formatCartError({ kind: 'out_of_stock', product: requireProduct(4) }),
  'リネンのふきん は在庫切れです'
);
check(
  '問題5: insufficient_stock の文言',
  formatCartError({ kind: 'insufficient_stock', product: requireProduct(3), requested: 4 }),
  'マグカップ の在庫が足りません（在庫3点 / 希望4点）'
);

// 小数の数量も invalid_quantity になる
const q5Fraction = addToCart([], requireProduct(3), 1.5);
check(
  '問題5: 小数の数量',
  q5Fraction.kind === 'error' ? q5Fraction.error.kind : 'ok',
  'invalid_quantity'
);

const Q5_ATTEMPTS: readonly { label: string; productId: number; quantity: number }[] = [
  { label: '①', productId: 3, quantity: 2 },
  { label: '②', productId: 4, quantity: 1 },
  { label: '③', productId: 3, quantity: 1 },
  { label: '④', productId: 3, quantity: 1 },
  { label: '⑤', productId: 1, quantity: 0 },
  { label: '⑥', productId: 1, quantity: 11 },
  { label: '⑦', productId: 1, quantity: 2 },
];

let q5Lines: readonly CartLine[] = [];
const q5Output: string[] = [];

for (const attempt of Q5_ATTEMPTS) {
  const product = requireProduct(attempt.productId);
  const head = `${attempt.label} ${product.name} × ${attempt.quantity} →`;
  const result = addToCart(q5Lines, product, attempt.quantity);

  if (result.kind === 'error') {
    q5Output.push(`${head} NG ${formatCartError(result.error)}`);
    continue;
  }
  q5Lines = result.value;
  q5Output.push(`${head} OK（明細${q5Lines.length}件 / 小計${calcCartSubtotal(q5Lines)}円）`);
}

const q5Rank = resolveMemberRank(21000);
const q5Percent = discountPercentByRank(q5Rank);
const q5Summary = buildPaymentSummary(q5Lines, makePercentDiscount(q5Percent));

q5Output.push(
  `支払い: 小計${q5Summary.subtotal}円 / 割引${q5Summary.discountAmount}円（${q5Rank} ${q5Percent}%）/ ` +
    `税${q5Summary.tax}円 / 税込${q5Summary.totalWithTax}円 / ` +
    `送料${q5Summary.shippingFee}円 / お支払い${q5Summary.payableAmount}円`
);

// 支払総額の1ステップずつの検算（解説に書いた数値）
check('問題5 手順1 小計', q5Summary.subtotal, 8010);
check('問題5 手順2 割引額（5%）', q5Summary.discountAmount, 400);
check('問題5 手順3 割引後小計', q5Summary.discountedTotal, 7610);
check('問題5 手順4 消費税', q5Summary.tax, 761);
check('問題5 手順5 税込商品合計', q5Summary.totalWithTax, 8371);
check('問題5 手順6 送料', q5Summary.shippingFee, 0);
check('問題5 手順7 支払総額', q5Summary.payableAmount, 8371);
check('問題5: 同じ商品は1明細にまとまる', q5Lines.length, 2);

check(
  '問題5の出力',
  q5Output.join('\n'),
  [
    '① マグカップ × 2 → OK（明細1件 / 小計4700円）',
    '② リネンのふきん × 1 → NG リネンのふきん は在庫切れです',
    '③ マグカップ × 1 → OK（明細1件 / 小計7050円）',
    '④ マグカップ × 1 → NG マグカップ の在庫が足りません（在庫3点 / 希望4点）',
    '⑤ ラベンダーの石けん × 0 → NG 数量は1以上の整数で指定してください（指定: 0）',
    '⑥ ラベンダーの石けん × 11 → NG 1商品あたり10点までです（指定: 11）',
    '⑦ ラベンダーの石けん × 2 → OK（明細2件 / 小計8010円）',
    '支払い: 小計8010円 / 割引400円（silver 5%）/ 税761円 / 税込8371円 / 送料0円 / お支払い8371円',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題6：Cart クラスで不変条件を守る（S15・S09・S13・S10）
// ---------------------------------------------------------------------------
class Cart {
  #lines: CartLine[];

  private constructor(lines: CartLine[]) {
    this.#lines = lines;
  }

  static empty(): Cart {
    return new Cart([]);
  }

  get lines(): readonly CartLine[] {
    return [...this.#lines];
  }

  get lineCount(): number {
    return this.#lines.length;
  }

  get itemCount(): number {
    return this.#lines.reduce((total, line) => total + line.quantity, 0);
  }

  get subtotal(): number {
    return calcCartSubtotal(this.#lines);
  }

  add(product: Product, quantity: number): Result<Cart, CartError> {
    const result = addToCart(this.#lines, product, quantity);
    if (result.kind === 'error') {
      return result;
    }
    return { kind: 'ok', value: new Cart(result.value) };
  }

  summary(rule: DiscountRule): PaymentSummary {
    return buildPaymentSummary(this.#lines, rule);
  }
}

class LegacyCart {
  private lines: CartLine[] = [];

  get lineCount(): number {
    return this.lines.length;
  }
}

function describeCart(label: string, cart: Cart, note: string): string {
  return `${label}: 明細${cart.lineCount}件 / ${cart.itemCount}点 / 小計${cart.subtotal}円${note}`;
}

// @ts-expect-error コンストラクタが private なので外から new できない
const q6Direct = new Cart([]);
check('問題6: private constructor は外から呼べない', q6Direct.lineCount, 0);

const q6Empty = Cart.empty();
const q6Step1 = q6Empty.add(requireProduct(3), 2);
if (q6Step1.kind === 'error') {
  throw new Error(formatCartError(q6Step1.error));
}
const q6Step2 = q6Step1.value.add(requireProduct(3), 1);
if (q6Step2.kind === 'error') {
  throw new Error(formatCartError(q6Step2.error));
}
const q6Step3 = q6Step2.value.add(requireProduct(3), 1);
const q6Step4 = q6Step2.value.add(requireProduct(1), 2);
if (q6Step4.kind === 'error') {
  throw new Error(formatCartError(q6Step4.error));
}
const q6Cart = q6Step4.value;

// 取り出した明細はコピー。書き換えてもカートは無傷
const q6Copied = [...q6Cart.lines];
q6Copied.pop();
check('問題6: コピーを書き換えても明細は減らない', q6Cart.lineCount, 2);
check('問題6: コピーを書き換えても小計は変わらない', q6Cart.subtotal, 8010);
check('問題6: add は自分自身を書き換えない', q6Step1.value.itemCount, 2);
check('問題6: 失敗しても元のカートは無傷', q6Step2.value.itemCount, 3);

// @ts-expect-error readonly の配列に push は無い
q6Cart.lines.push({ product: requireProduct(1), quantity: 1 });
check('問題6: push しても明細は増えない（コピーに対する操作）', q6Cart.lineCount, 2);

const q6Legacy = new LegacyCart();
// @ts-expect-error private フィールドには外からアクセスできない
const q6PrivatePeek = q6Legacy.lines;
check('問題6: private は実行時には読めてしまう', q6PrivatePeek.length, 0);
check('問題6: private は Object.keys に出る', Object.keys(q6Legacy).join(', '), 'lines');
check('問題6: # は Object.keys に出ない', Object.keys(q6Cart).length, 0);

const q6Output = [
  describeCart('空のカート', q6Empty, ''),
  describeCart('① マグカップ×2', q6Step1.value, ''),
  describeCart('② マグカップ×1', q6Step2.value, '（同じ商品は1明細にまとめる）'),
  q6Step3.kind === 'error'
    ? `③ マグカップ×1: 失敗（${formatCartError(q6Step3.error)}）/ ` +
      `カートは 明細${q6Step2.value.lineCount}件 / ${q6Step2.value.itemCount}点 のまま`
    : '③ は失敗するはずです',
  describeCart('④ ラベンダーの石けん×2', q6Cart, ''),
  `取り出した明細から1件消しても: 明細${q6Cart.lineCount}件 / 小計${q6Cart.subtotal}円`,
  `private は Object.keys に出る: ${Object.keys(q6Legacy).join(', ')} / ` +
    `# は出ない: ${Object.keys(q6Cart).length === 0 ? '(なし)' : Object.keys(q6Cart).join(', ')}`,
];

check(
  '問題6の出力',
  q6Output.join('\n'),
  [
    '空のカート: 明細0件 / 0点 / 小計0円',
    '① マグカップ×2: 明細1件 / 2点 / 小計4700円',
    '② マグカップ×1: 明細1件 / 3点 / 小計7050円（同じ商品は1明細にまとめる）',
    '③ マグカップ×1: 失敗（マグカップ の在庫が足りません（在庫3点 / 希望4点））/ カートは 明細1件 / 3点 のまま',
    '④ ラベンダーの石けん×2: 明細2件 / 5点 / 小計8010円',
    '取り出した明細から1件消しても: 明細2件 / 小計8010円',
    'private は Object.keys に出る: lines / # は出ない: (なし)',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題7：不正な状態遷移を「呼べない」ようにする（S11〜S15 の総合）
// ---------------------------------------------------------------------------
function placeOrder(
  cart: Cart,
  orderId: number,
  userId: number,
  rank: MemberRank,
  now: string
): Result<PendingOrder, string> {
  if (cart.lineCount === 0) {
    return { kind: 'error', error: 'カートが空です' };
  }
  const summary = cart.summary(makePercentDiscount(discountPercentByRank(rank)));
  return {
    kind: 'ok',
    value: {
      kind: 'pending',
      id: orderId,
      userId,
      totalAmount: summary.payableAmount,
      createdAt: now,
    },
  };
}

function payOrder(order: PendingOrder, paidAt: string): PaidOrder {
  return { ...order, kind: 'paid', paidAt };
}

function shipOrder(order: PaidOrder, shippedAt: string): ShippedOrder {
  return { ...order, kind: 'shipped', shippedAt };
}

function cancelOrder(
  order: PendingOrder | PaidOrder,
  reason: string,
  cancelledAt: string
): CancelledOrder {
  const base: OrderBase = {
    id: order.id,
    userId: order.userId,
    totalAmount: order.totalAmount,
    createdAt: order.createdAt,
  };
  return { ...base, kind: 'cancelled', cancelledAt, reason };
}

function countByStatus(orders: readonly Order[]): Record<OrderStatus, number> {
  const counts: Record<OrderStatus, number> = { pending: 0, paid: 0, shipped: 0, cancelled: 0 };
  for (const order of orders) {
    counts[order.kind] += 1;
  }
  return counts;
}

function buildCart(items: readonly { productId: number; quantity: number }[]): Cart {
  let cart = Cart.empty();
  for (const item of items) {
    const result = cart.add(requireProduct(item.productId), item.quantity);
    if (result.kind === 'error') {
      throw new Error(formatCartError(result.error));
    }
    cart = result.value;
  }
  return cart;
}

const q7MainCart = buildCart([
  { productId: 3, quantity: 3 },
  { productId: 1, quantity: 2 },
]);
const q7Placed = placeOrder(q7MainCart, 2001, 1, resolveMemberRank(21000), '2026-08-26');
if (q7Placed.kind === 'error') {
  throw new Error(q7Placed.error);
}
const q7Pending = q7Placed.value;
const q7Paid = payOrder(q7Pending, '2026-08-27');
const q7Shipped = shipOrder(q7Paid, '2026-08-28');
const q7EmptyResult = placeOrder(Cart.empty(), 2003, 1, 'none', '2026-08-26');

const q7SecondCart = buildCart([{ productId: 1, quantity: 2 }]);
const q7Second = placeOrder(q7SecondCart, 2002, 2, resolveMemberRank(1000), '2026-08-26');
if (q7Second.kind === 'error') {
  throw new Error(q7Second.error);
}
const q7Cancelled = cancelOrder(q7Second.value, '都合により', '2026-08-27');
const q7Counts = countByStatus([q7Shipped, q7Cancelled]);

// 遷移の戻り値の型が具体的であること（連鎖が型でつながる）
const _q7Paid: PaidOrder = payOrder(q7Pending, '2026-08-27');
const _q7Shipped: ShippedOrder = shipOrder(_q7Paid, '2026-08-28');
check('問題7: 遷移の連鎖は型でつながる', _q7Shipped.shippedAt, '2026-08-28');

// @ts-expect-error 発送済みの注文に payOrder は渡せない
const q7Wrong = payOrder(q7Shipped, '2026-08-29');
check('問題7: 型で止めないと実行時には通ってしまう', q7Wrong.kind, 'paid');

// @ts-expect-error 未払いの注文は発送できない
const q7WrongShip = shipOrder(q7Pending, '2026-08-29');
check('問題7: 未払いからの発送も型で止まる', q7WrongShip.kind, 'shipped');

// @ts-expect-error キャンセル済みの注文はもうキャンセルできない
const q7WrongCancel = cancelOrder(q7Cancelled, 'やっぱり', '2026-08-29');
check('問題7: 終着点からの遷移も型で止まる', q7WrongCancel.kind, 'cancelled');

check('問題7: 支払総額（silver 5%）', q7Pending.totalAmount, 8371);
check('問題7: 2件目の支払総額（割引なし・送料あり）', q7Second.value.totalAmount, 1556);
check('問題7: キャンセルは入金日を引きずらない', Object.keys(q7Cancelled).includes('paidAt'), false);
check('問題7: 元の注文は書き換わらない', q7Pending.kind, 'pending');
check('問題7: 空のカートは失敗する', q7EmptyResult.kind, 'error');
check('問題7: 集計（shipped）', q7Counts.shipped, 1);
check('問題7: 集計（cancelled）', q7Counts.cancelled, 1);
check('問題7: 集計（pending）', q7Counts.pending, 0);

const q7Output = [
  `① 注文を作成: ${describeOrder(q7Pending)}`,
  `② 入金を記録: ${describeOrder(q7Paid)}`,
  `③ 発送を記録: ${describeOrder(q7Shipped)}`,
  `④ 空のカートで注文: ${
    q7EmptyResult.kind === 'error' ? `失敗（${q7EmptyResult.error}）` : '成功'
  }`,
  `⑤ 未払いのままキャンセル: ${describeOrder(q7Cancelled)}`,
  '⑥ 発送済みの注文に payOrder は渡せない（tsc --noEmit が TS2345 で止まる）',
  `⑦ ステータス別の件数: ${ORDER_STATUSES.map(
    (status) => `${status} ${q7Counts[status]}件`
  ).join(' / ')}`,
];

check(
  '問題7の出力',
  q7Output.join('\n'),
  [
    '① 注文を作成: #2001 お支払いをお待ちしています（8371円）',
    '② 入金を記録: #2001 お支払いを確認しました（入金 2026-08-27）',
    '③ 発送を記録: #2001 発送済みです（入金 2026-08-27 / 出荷 2026-08-28）',
    '④ 空のカートで注文: 失敗（カートが空です）',
    '⑤ 未払いのままキャンセル: #2002 キャンセルされました（理由: 都合により）',
    '⑥ 発送済みの注文に payOrder は渡せない（tsc --noEmit が TS2345 で止まる）',
    '⑦ ステータス別の件数: pending 0件 / paid 0件 / shipped 1件 / cancelled 1件',
  ].join('\n')
);

console.log('review02: ok');
