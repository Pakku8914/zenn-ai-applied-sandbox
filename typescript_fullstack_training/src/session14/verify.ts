/**
 * セッション14「ユーティリティ型と型レベルの操作」の検証スクリプト。
 *
 * 本文（046）と練習問題の解答（048）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * この章は「型レベルの操作」が主題なので、実行時の出力だけでは検証にならない。
 * そのためファイル後半に「型の主張」をまとめてある。
 *   - 正しい型であること   … const _check: 期待する型 = 値;  （代入できればOK）
 *   - 誤りが弾かれること   … // @ts-expect-error を置いた次の行
 *     （@ts-expect-error はエラーが出ないと逆に失敗するので、型の主張の証明になる）
 * これらは npx tsc --noEmit で検証される（verify-all.sh は tsc を先に通す）。
 *
 * 実行: docker compose exec ts npx tsx src/session14/verify.ts
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
// この章で使う共通データ（本文「この章で使う共通データ」と同じ）
// この章は Product の7フィールドすべてを使う（Omit で id を除く例のため）
// ---------------------------------------------------------------------------
type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

const products: readonly Product[] = [
  {
    id: 1,
    name: 'ラベンダーの石けん',
    price: 480,
    stock: 24,
    categoryId: 1,
    description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
    imageUrl: '/images/products/lavender-soap.png',
  },
  {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    stock: 12,
    categoryId: 1,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png',
  },
  {
    id: 3,
    name: 'マグカップ',
    price: 2350,
    stock: 3,
    categoryId: 2,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
    imageUrl: '/images/products/mug.png',
  },
  {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
    categoryId: 3,
    description: '洗うほどやわらかくなるリネン100%のふきんです。',
    imageUrl: '/images/products/linen-cloth.png',
  },
  {
    id: 5,
    name: 'コットンのトートバッグ',
    price: 2800,
    stock: 5,
    categoryId: 3,
    description: 'A4サイズが入る、しっかりした厚手のトートバッグです。',
    imageUrl: '/images/products/tote-bag.png',
  },
];

/** 例でよく使う1件（マスタの id=3） */
const mug: Product = {
  id: 3,
  name: 'マグカップ',
  price: 2350,
  stock: 3,
  categoryId: 2,
  description: '厚みのある陶器で、冷めにくいマグカップです。',
  imageUrl: '/images/products/mug.png',
};

// ---------------------------------------------------------------------------
// 1節：型の位置に書く typeof とインデックスアクセス型
// ---------------------------------------------------------------------------
const ORDER_STATUSES = ['pending', 'paid', 'shipped', 'cancelled'] as const;
const MEMBER_RANKS = ['gold', 'silver', 'bronze', 'none'] as const;
const CATEGORY_SLUGS = ['bath-body', 'kitchen', 'fabric'] as const;

type OrderStatus = (typeof ORDER_STATUSES)[number];
type MemberRank = (typeof MEMBER_RANKS)[number];
type CategorySlug = (typeof CATEGORY_SLUGS)[number];

type Price = Product['price'];
type Name = Product['name'];
type ProductKey = keyof Product;
type IdOrName = Product['id' | 'name'];

const productKeys: readonly ProductKey[] = [
  'id',
  'name',
  'price',
  'stock',
  'description',
  'imageUrl',
  'categoryId',
];

function bodyIndexedAccess(): string {
  const somePrice: Price = 2350;
  const someName: Name = 'マグカップ';
  return `型から取り出した値の型で受けた: ${someName} / ${somePrice}円`;
}

checkString(
  '本文1節: インデックスアクセス型で受けた値',
  bodyIndexedAccess(),
  '型から取り出した値の型で受けた: マグカップ / 2350円'
);

function bodyTypeQuery(): string {
  const status: OrderStatus = 'paid';
  const rank: MemberRank = 'silver';

  return [
    `ステータスの一覧: ${ORDER_STATUSES.join(' / ')}`,
    `先頭のステータス: ${ORDER_STATUSES[0]}`,
    `いま扱う注文: ${status} / 会員ランク: ${rank}`,
  ].join('\n');
}

checkString(
  '本文1節: as const 配列から作った型',
  bodyTypeQuery(),
  'ステータスの一覧: pending / paid / shipped / cancelled\n' +
    '先頭のステータス: pending\n' +
    'いま扱う注文: paid / 会員ランク: silver'
);

checkNumber('本文1節: Product のキー数', productKeys.length, 7);

// ---------------------------------------------------------------------------
// 2節：Pick と Omit（問題2でも同じ型・同じ関数を使う）
// ---------------------------------------------------------------------------
type ProductInput = Omit<Product, 'id'>;
type ProductSummary = Pick<Product, 'id' | 'name' | 'price'>;
type ProductCard = Pick<Product, 'name' | 'price' | 'imageUrl'>;

const addProduct = (items: readonly Product[], input: ProductInput): Product[] => {
  const nextId = items.reduce((max, item) => (item.id > max ? item.id : max), 0) + 1;
  return [...items, { id: nextId, ...input }];
};

const toSummary = (product: Product): ProductSummary => ({
  id: product.id,
  name: product.name,
  price: product.price,
});

const toCard = (product: Product): ProductCard => ({
  name: product.name,
  price: product.price,
  imageUrl: product.imageUrl,
});

const bathSaltInput: ProductInput = {
  name: '入浴剤',
  price: 650,
  stock: 10,
  description: '炭酸ガスでゆっくり温まる入浴剤です。',
  imageUrl: '/images/products/no-image.png',
  categoryId: 1,
};

const summaryLine = products
  .map(toSummary)
  .map((item) => `${item.id}:${item.name}(${item.price}円)`)
  .join(' / ');

function bodyPickOmit(): string {
  const nextProducts = addProduct(products, bathSaltInput);
  return [`商品数: ${products.length}点 → ${nextProducts.length}点`, summaryLine].join('\n');
}

checkString(
  '本文2節: Omit と Pick で作った派生型',
  bodyPickOmit(),
  '商品数: 5点 → 6点\n' +
    '1:ラベンダーの石けん(480円) / 2:ハンドクリーム(1800円) / 3:マグカップ(2350円) / ' +
    '4:リネンのふきん(990円) / 5:コットンのトートバッグ(2800円)'
);

// addProduct は元の配列を変えない
checkNumber('本文2節: addProduct は非破壊', products.length, 5);

// ---------------------------------------------------------------------------
// 2節（続き）：Partial / Required / Readonly
// ---------------------------------------------------------------------------
const applyProductPatch = (product: Product, patch: Partial<Omit<Product, 'id'>>): Product => ({
  ...product,
  ...patch,
});

function bodyModifiers(): string {
  const updated = applyProductPatch(mug, { price: 2500, stock: 8 });
  const displayMug: Readonly<Product> = mug;

  return [
    `変更前: ${mug.name} ${mug.price}円 / 在庫${mug.stock}点`,
    `変更後: ${updated.name} ${updated.price}円 / 在庫${updated.stock}点`,
    `元の値は変わらない: ${mug.price}円 / 在庫${mug.stock}点`,
    `表示専用: ${displayMug.name}`,
  ].join('\n');
}

checkString(
  '本文2節: Partial で作った更新用の型',
  bodyModifiers(),
  '変更前: マグカップ 2350円 / 在庫3点\n' +
    '変更後: マグカップ 2500円 / 在庫8点\n' +
    '元の値は変わらない: 2350円 / 在庫3点\n' +
    '表示専用: マグカップ'
);

// ---------------------------------------------------------------------------
// 3節：Record（Bad はインデックスシグネチャ版）
// ---------------------------------------------------------------------------
const BAD_DISCOUNT_PERCENT: { [rank: string]: number } = {
  gold: 10,
  silver: 5,
  bronze: 3,
  // none を書き忘れてもコンパイルは通る
};

const badDiscountPercentByRank = (rank: MemberRank): number => {
  const percent = BAD_DISCOUNT_PERCENT[rank]; // number | undefined
  return percent ?? 0;
};

checkNumber('本文3節 Bad: 書き忘れが 0% として吸収される', badDiscountPercentByRank('none'), 0);
checkNumber('本文3節 Bad: 書いてあるランクは読める', badDiscountPercentByRank('gold'), 10);

const DISCOUNT_PERCENT_BY_RANK: Record<MemberRank, number> = {
  gold: 10,
  silver: 5,
  bronze: 3,
  none: 0,
};

const CATEGORY_NAME_BY_SLUG: Record<CategorySlug, string> = {
  'bath-body': 'バス・ボディケア',
  kitchen: 'キッチン雑貨',
  fabric: 'ファブリック',
};

const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  pending: '支払い待ち',
  paid: '支払い済み',
  shipped: '発送済み',
  cancelled: 'キャンセル',
};

const CAN_CANCEL: Record<OrderStatus, boolean> = {
  pending: true,
  paid: true,
  shipped: false,
  cancelled: false,
};

const discountPercentByRank = (rank: MemberRank): number => DISCOUNT_PERCENT_BY_RANK[rank];

function bodyRecord(): string {
  const lines: string[] = [];

  for (const rank of MEMBER_RANKS) {
    lines.push(`${rank}: ${discountPercentByRank(rank)}%`);
  }
  for (const slug of CATEGORY_SLUGS) {
    lines.push(`${slug} → ${CATEGORY_NAME_BY_SLUG[slug]}`);
  }

  return lines.join('\n');
}

checkString(
  '本文3節 Good: Record で作った対応表',
  bodyRecord(),
  'gold: 10%\n' +
    'silver: 5%\n' +
    'bronze: 3%\n' +
    'none: 0%\n' +
    'bath-body → バス・ボディケア\n' +
    'kitchen → キッチン雑貨\n' +
    'fabric → ファブリック'
);

// ---------------------------------------------------------------------------
// 4節：ReturnType / Parameters / Awaited（問題5でも同じ関数を使う）
// ---------------------------------------------------------------------------
type DiscountRule = (subtotal: number) => number;

const makePercentDiscount =
  (percent: number): DiscountRule =>
  (subtotal) =>
    Math.floor((subtotal * percent) / 100);

const noDiscount: DiscountRule = () => 0;

const calcLineTotal = (price: number, quantity: number): number => price * quantity;

const calcSubtotal = <T extends { price: number; quantity: number }>(
  lines: readonly T[]
): number => lines.reduce((total, line) => total + calcLineTotal(line.price, line.quantity), 0);

const calcShippingFee = (totalWithTax: number): number =>
  totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;

/** 支払いの内訳（計算手順1〜7）。戻り値の型注釈はあえて書かない */
const buildPaymentSummary = (
  lines: readonly { price: number; quantity: number }[],
  rule: DiscountRule
) => {
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
};

type PaymentSummary = ReturnType<typeof buildPaymentSummary>;
type ReceiptLine = Pick<PaymentSummary, 'subtotal' | 'discountAmount' | 'payableAmount'>;
type RuleArg = Parameters<typeof buildPaymentSummary>[1];
type LineTotalArgs = Parameters<typeof calcLineTotal>;
type FetchedProduct = Awaited<Promise<Product>>;

const cartLines = [
  { name: 'ラベンダーの石けん', price: 480, quantity: 2 },
  { name: 'ハンドクリーム', price: 1800, quantity: 1 },
  { name: 'コットンのトートバッグ', price: 2800, quantity: 1 },
];

const soapOnly = [{ name: 'ラベンダーの石けん', price: 480, quantity: 2 }];

const goldSummary = buildPaymentSummary(cartLines, makePercentDiscount(10));

function bodyFromFunction(): string {
  const receipt: ReceiptLine = {
    subtotal: goldSummary.subtotal,
    discountAmount: goldSummary.discountAmount,
    payableAmount: goldSummary.payableAmount,
  };

  return [
    `小計: ${goldSummary.subtotal}円`,
    `割引額: ${goldSummary.discountAmount}円`,
    `消費税: ${goldSummary.tax}円`,
    `お支払い金額: ${goldSummary.payableAmount}円`,
    `レシート: 小計${receipt.subtotal}円 → 支払${receipt.payableAmount}円`,
  ].join('\n');
}

checkString(
  '本文4節: ReturnType で導出した内訳',
  bodyFromFunction(),
  '小計: 5560円\n' +
    '割引額: 556円\n' +
    '消費税: 500円\n' +
    'お支払い金額: 5504円\n' +
    'レシート: 小計5560円 → 支払5504円'
);

// 計算手順の内訳（本文の表に書いた数値）
checkNumber('本文4節 手順1 小計', calcSubtotal(cartLines), 5560);
checkNumber('本文4節 手順2 割引額', makePercentDiscount(10)(5560), 556);
checkNumber('本文4節 手順3 割引後小計', goldSummary.discountedTotal, 5004);
checkNumber('本文4節 手順4 消費税', Math.floor(5004 * TAX_RATE), 500);
checkNumber('本文4節 手順5 税込商品合計', goldSummary.totalWithTax, 5504);
checkNumber('本文4節 手順6 送料', calcShippingFee(5504), 0);
checkNumber('本文4節 手順7 支払総額', goldSummary.payableAmount, 5504);

function bodyParameters(): string {
  const args: LineTotalArgs = [480, 2];
  const goldRule: RuleArg = makePercentDiscount(10);

  return [
    `スプレッドで呼べる: ${calcLineTotal(...args)}円`,
    `gold の割引額: ${goldRule(5560)}円`,
  ].join('\n');
}

checkString(
  '本文4節: Parameters とタプル型',
  bodyParameters(),
  'スプレッドで呼べる: 960円\ngold の割引額: 556円'
);

function bodyAwaited(): string {
  const fetched: FetchedProduct = mug;
  return `Promise の中身の型で受けた: ${fetched.name}`;
}

checkString(
  '本文4節: Awaited で包みを剥がす',
  bodyAwaited(),
  'Promise の中身の型で受けた: マグカップ'
);

// ---------------------------------------------------------------------------
// 5節：mapped type（問題6でも同じ型を使う）
// ---------------------------------------------------------------------------
type MyReadonly<T> = { readonly [K in keyof T]: T[K] };
type MyPartial<T> = { [K in keyof T]?: T[K] };
type Mutable<T> = { -readonly [K in keyof T]: T[K] };
type Concrete<T> = { [K in keyof T]-?: T[K] };
type Stringify<T> = { [K in keyof T]: string };

function bodyMappedType(): string {
  const readonlyMug: Readonly<Product> = mug;
  const editableMug: Mutable<Readonly<Product>> = { ...readonlyMug };
  const before = `編集前: ${editableMug.price}円`;
  editableMug.price = 2500;
  return [before, `編集後: ${editableMug.price}円`].join('\n');
}

checkString('本文5節: Mutable で readonly を外す', bodyMappedType(), '編集前: 2350円\n編集後: 2500円');

// 元の mug は変わっていない（コピーを書き換えているだけ）
checkNumber('本文5節: 元の商品は変わらない', mug.price, 2350);

// ---------------------------------------------------------------------------
// 6節：条件型と infer
// ---------------------------------------------------------------------------
type ElementType<T> = T extends readonly (infer U)[] ? U : never;

function bodyConditionalType(): string {
  const firstProduct: ElementType<typeof products> = mug;
  const firstStatus: ElementType<typeof ORDER_STATUSES> = 'pending';
  return `要素の型で受けた: ${firstProduct.name}（${firstProduct.price}円） / ${firstStatus}`;
}

checkString(
  '本文6節: infer で要素の型を取り出す',
  bodyConditionalType(),
  '要素の型で受けた: マグカップ（2350円） / pending'
);

// ---------------------------------------------------------------------------
// 7節：テンプレートリテラル型
// ---------------------------------------------------------------------------
type ProductImagePath = `/images/products/${string}.png`;
type CategoryPagePath = `/categories/${CategorySlug}`;
type ProductPagePath = `/products/${number}`;

/** Product の imageUrl だけ型を厳しくしたもの（本文7節） */
type BodyStrictProduct = Omit<Product, 'imageUrl'> & { imageUrl: ProductImagePath };

const toImagePath = (slug: string): ProductImagePath => `/images/products/${slug}.png`;
const toCategoryPath = (slug: CategorySlug): CategoryPagePath => `/categories/${slug}`;
const toProductPath = (id: number): ProductPagePath => `/products/${id}`;

function bodyTemplateLiteralHead(): string {
  const okPath: ProductImagePath = '/images/products/mug.png';
  const noImage: ProductImagePath = '/images/products/no-image.png';
  return `画像パス: ${okPath} / 既定: ${noImage}`;
}

checkString(
  '本文7節: テンプレートリテラル型に代入できるパス',
  bodyTemplateLiteralHead(),
  '画像パス: /images/products/mug.png / 既定: /images/products/no-image.png'
);

function bodyTemplateLiteral(): string {
  const strictMug: BodyStrictProduct = { ...mug, imageUrl: '/images/products/mug.png' };

  return [
    toImagePath('lavender-soap'),
    toCategoryPath('fabric'),
    toProductPath(3),
    `厳しい型の商品: ${strictMug.name} → ${strictMug.imageUrl}`,
  ].join('\n');
}

checkString(
  '本文7節: パスを組み立てる関数',
  bodyTemplateLiteral(),
  '/images/products/lavender-soap.png\n' +
    '/categories/fabric\n' +
    '/products/3\n' +
    '厳しい型の商品: マグカップ → /images/products/mug.png'
);

// ---------------------------------------------------------------------------
// 問題1：typeof とインデックスアクセス型でイディオムを分解する
// ---------------------------------------------------------------------------
function solveQ1(): string {
  const somePrice: Price = mug.price;
  const someId: IdOrName = mug.id;
  const someName: IdOrName = mug.name;

  return [
    `ステータス4種: ${ORDER_STATUSES.join(' / ')}`,
    `会員ランク4種: ${MEMBER_RANKS.join(' / ')}`,
    `カテゴリ3種: ${CATEGORY_SLUGS.join(' / ')}`,
    `先頭のステータス: ${ORDER_STATUSES[0]}`,
    `Product のキー数: ${productKeys.length}`,
    `price の型で受けた値: ${somePrice}`,
    `id か name の型で受けた値: ${someId} / ${someName}`,
  ].join('\n');
}

checkString(
  '問題1: 出力7行',
  solveQ1(),
  'ステータス4種: pending / paid / shipped / cancelled\n' +
    '会員ランク4種: gold / silver / bronze / none\n' +
    'カテゴリ3種: bath-body / kitchen / fabric\n' +
    '先頭のステータス: pending\n' +
    'Product のキー数: 7\n' +
    'price の型で受けた値: 2350\n' +
    'id か name の型で受けた値: 3 / マグカップ'
);

// ---------------------------------------------------------------------------
// 問題2：Pick と Omit で派生型を作る
// ---------------------------------------------------------------------------
function solveQ2(): string {
  const nextProducts = addProduct(products, bathSaltInput);
  const added = nextProducts.find((item) => item.name === bathSaltInput.name);
  const card = toCard(mug);

  return [
    `登録前: ${bathSaltInput.name}（${bathSaltInput.price}円 / 在庫${bathSaltInput.stock}点）`,
    `登録後: id=${added === undefined ? '?' : added.id} ${bathSaltInput.name}`,
    `商品数: ${products.length}点 → ${nextProducts.length}点`,
    `一覧: ${summaryLine}`,
    `カード: ${card.name} / ${card.price}円 / ${card.imageUrl}`,
  ].join('\n');
}

checkString(
  '問題2: 出力5行',
  solveQ2(),
  '登録前: 入浴剤（650円 / 在庫10点）\n' +
    '登録後: id=6 入浴剤\n' +
    '商品数: 5点 → 6点\n' +
    '一覧: 1:ラベンダーの石けん(480円) / 2:ハンドクリーム(1800円) / 3:マグカップ(2350円) / ' +
    '4:リネンのふきん(990円) / 5:コットンのトートバッグ(2800円)\n' +
    'カード: マグカップ / 2350円 / /images/products/mug.png'
);

// Omit のキー名のタイポは検出されない（Product と同じ形になる）
type TypoOmit = Omit<Product, 'idd'>;
const stillHasId: TypoOmit = { ...mug };
checkNumber('問題2: Omit のタイポは通ってしまう', stillHasId.id, 3);

// ---------------------------------------------------------------------------
// 問題3：Partial の罠を避けた更新用の型
// ---------------------------------------------------------------------------
type ProductPatch = Partial<Omit<Product, 'id'>> & { id: number };

const COMPARE_KEYS: readonly (keyof Product)[] = [
  'name',
  'price',
  'stock',
  'description',
  'imageUrl',
  'categoryId',
];

const applyPatch = (items: readonly Product[], patch: ProductPatch): readonly Product[] => {
  if (!items.some((item) => item.id === patch.id)) {
    return items;
  }
  return items.map((item) => (item.id === patch.id ? { ...item, ...patch } : item));
};

const describeChanges = (before: Product, after: Product): string => {
  const changed = COMPARE_KEYS.filter((key) => before[key] !== after[key]);
  return changed.length === 0 ? '変更なし' : changed.join(' / ');
};

const q3Patches: readonly ProductPatch[] = [
  { id: 3, price: 2500 },
  { id: 4, stock: 12, description: '洗うほどやわらかくなる、台所の相棒です。' },
  { id: 99, price: 100 },
];

const describeState = (items: readonly Product[]): string => {
  const target = items.find((item) => item.id === 3);
  const cloth = items.find((item) => item.id === 4);
  const left = target === undefined ? '?' : `${target.name} ${target.price}円`;
  const right = cloth === undefined ? '?' : `${cloth.name} 在庫${cloth.stock}点`;
  return `${left} / ${right}`;
};

function solveQ3(): string {
  const lines: string[] = [];
  let current: readonly Product[] = products;

  for (const patch of q3Patches) {
    const before = current.find((item) => item.id === patch.id);

    if (before === undefined) {
      lines.push(`id=${patch.id}: 該当する商品がありません`);
      continue;
    }

    const next = applyPatch(current, patch);
    const after = next.find((item) => item.id === patch.id);
    const changes = after === undefined ? '変更なし' : describeChanges(before, after);
    lines.push(`id=${patch.id}: ${changes} を変更（${before.name}）`);
    current = next;
  }

  lines.push(`更新後: ${describeState(current)}`);
  lines.push(`元の配列: ${describeState(products)}`);

  return lines.join('\n');
}

checkString(
  '問題3: 出力5行',
  solveQ3(),
  'id=3: price を変更（マグカップ）\n' +
    'id=4: stock / description を変更（リネンのふきん）\n' +
    'id=99: 該当する商品がありません\n' +
    '更新後: マグカップ 2500円 / リネンのふきん 在庫12点\n' +
    '元の配列: マグカップ 2350円 / リネンのふきん 在庫0点'
);

// 該当なしのパッチは「同じ配列」を返す（参照が変わらない）
checkBoolean(
  '問題3: 該当なしなら元の配列がそのまま返る',
  applyPatch(products, { id: 99, price: 100 }) === products,
  true
);

// 変更が無ければ '変更なし'
checkString('問題3: 変更なしの判定', describeChanges(mug, { ...mug }), '変更なし');

// 別解：存在確認を省くと、該当なしでも新しい配列が返る
const applyPatchMapOnly = (
  items: readonly Product[],
  patch: ProductPatch
): readonly Product[] => items.map((item) => (item.id === patch.id ? { ...item, ...patch } : item));

checkBoolean(
  '問題3 別解: map だけだと参照が変わる',
  applyPatchMapOnly(products, { id: 99, price: 100 }) === products,
  false
);

// ---------------------------------------------------------------------------
// 問題4：Record で追加漏れを検出できる対応表を作る
// ---------------------------------------------------------------------------
const describeStatus = (status: OrderStatus): string =>
  `${ORDER_STATUS_LABEL[status]}（${CAN_CANCEL[status] ? 'キャンセル可' : 'キャンセル不可'}）`;

function solveQ4(): string {
  const lines: string[] = [];

  for (const status of ORDER_STATUSES) {
    lines.push(`${status}: ${describeStatus(status)}`);
  }

  lines.push(
    `割引率: ${MEMBER_RANKS.map((rank) => `${rank}=${discountPercentByRank(rank)}%`).join(' / ')}`
  );
  lines.push(
    `カテゴリ名: ${CATEGORY_SLUGS.map((slug) => `${slug} → ${CATEGORY_NAME_BY_SLUG[slug]}`).join(
      ' / '
    )}`
  );

  return lines.join('\n');
}

checkString(
  '問題4: 出力6行',
  solveQ4(),
  'pending: 支払い待ち（キャンセル可）\n' +
    'paid: 支払い済み（キャンセル可）\n' +
    'shipped: 発送済み（キャンセル不可）\n' +
    'cancelled: キャンセル（キャンセル不可）\n' +
    '割引率: gold=10% / silver=5% / bronze=3% / none=0%\n' +
    'カテゴリ名: bath-body → バス・ボディケア / kitchen → キッチン雑貨 / fabric → ファブリック'
);

// 表は「キャンセルできるか」の仕様（requirements.md のステータス遷移）と一致する
checkBoolean('問題4: pending はキャンセル可', CAN_CANCEL.pending, true);
checkBoolean('問題4: paid はキャンセル可', CAN_CANCEL.paid, true);
checkBoolean('問題4: shipped はキャンセル不可', CAN_CANCEL.shipped, false);
checkBoolean('問題4: cancelled はキャンセル不可', CAN_CANCEL.cancelled, false);

// ---------------------------------------------------------------------------
// 問題5：ReturnType / Parameters / Awaited
// ---------------------------------------------------------------------------
const toReceiptLine = (summary: PaymentSummary): ReceiptLine => ({
  subtotal: summary.subtotal,
  discountAmount: summary.discountAmount,
  payableAmount: summary.payableAmount,
});

const formatSummary = (label: string, summary: PaymentSummary): string =>
  `[${label}] 小計${summary.subtotal}円 / 割引${summary.discountAmount}円 / ` +
  `税${summary.tax}円 / 送料${summary.shippingFee}円 / 支払${summary.payableAmount}円`;

function solveQ5(): string {
  const receipt = toReceiptLine(goldSummary);
  const goldRule: RuleArg = makePercentDiscount(10);
  const fetched: FetchedProduct = mug;

  return [
    formatSummary('gold', goldSummary),
    formatSummary('割引なし', buildPaymentSummary(cartLines, noDiscount)),
    formatSummary('石けん2点', buildPaymentSummary(soapOnly, noDiscount)),
    `レシート: 小計${receipt.subtotal}円 / 割引${receipt.discountAmount}円 / 支払${receipt.payableAmount}円`,
    `引数1の型で受けたルール: 5560円に対して${goldRule(5560)}円`,
    `Promise の中身の型で受けた: ${fetched.name}`,
  ].join('\n');
}

checkString(
  '問題5: 出力6行',
  solveQ5(),
  '[gold] 小計5560円 / 割引556円 / 税500円 / 送料0円 / 支払5504円\n' +
    '[割引なし] 小計5560円 / 割引0円 / 税556円 / 送料0円 / 支払6116円\n' +
    '[石けん2点] 小計960円 / 割引0円 / 税96円 / 送料500円 / 支払1556円\n' +
    'レシート: 小計5560円 / 割引556円 / 支払5504円\n' +
    '引数1の型で受けたルール: 5560円に対して556円\n' +
    'Promise の中身の型で受けた: マグカップ'
);

// 解答の内訳表に書いた数値
const q5NoDiscount = buildPaymentSummary(cartLines, noDiscount);
checkNumber('問題5 割引なし: 消費税', q5NoDiscount.tax, 556);
checkNumber('問題5 割引なし: 税込商品合計', q5NoDiscount.totalWithTax, 6116);
checkNumber('問題5 割引なし: 送料', q5NoDiscount.shippingFee, 0);
checkNumber('問題5 割引なし: 支払総額', q5NoDiscount.payableAmount, 6116);

const q5SoapOnly = buildPaymentSummary(soapOnly, noDiscount);
checkNumber('問題5 石けん2点: 小計', q5SoapOnly.subtotal, 960);
checkNumber('問題5 石けん2点: 消費税', q5SoapOnly.tax, 96);
checkNumber('問題5 石けん2点: 税込商品合計', q5SoapOnly.totalWithTax, 1056);
checkNumber('問題5 石けん2点: 送料（3000円未満なので500円）', q5SoapOnly.shippingFee, 500);
checkNumber('問題5 石けん2点: 支払総額', q5SoapOnly.payableAmount, 1556);

// 割引額は小計を超えない（Math.min の効き）
const q5HugeDiscount = buildPaymentSummary(soapOnly, () => 99999);
checkNumber('問題5: 割引額は小計を超えない', q5HugeDiscount.discountAmount, 960);
checkNumber('問題5: 支払総額は送料だけ残る', q5HugeDiscount.payableAmount, 500);

// ---------------------------------------------------------------------------
// 問題6：mapped type・条件型・テンプレートリテラル型で商品カタログを組み立てる
// ---------------------------------------------------------------------------
const toStringified = (product: Product): Stringify<Product> => ({
  id: String(product.id),
  name: product.name,
  price: String(product.price),
  stock: String(product.stock),
  description: product.description,
  imageUrl: product.imageUrl,
  categoryId: String(product.categoryId),
});

const CATEGORY_IDS = [1, 2, 3] as const;
type CategoryId = (typeof CATEGORY_IDS)[number]; // 1 | 2 | 3

const CATEGORY_SLUG_BY_ID: Record<CategoryId, CategorySlug> = {
  1: 'bath-body',
  2: 'kitchen',
  3: 'fabric',
};

const isCategoryId = (value: number): value is CategoryId =>
  CATEGORY_IDS.some((id) => id === value);

const toCategorySlug = (categoryId: number): CategorySlug | undefined =>
  isCategoryId(categoryId) ? CATEGORY_SLUG_BY_ID[categoryId] : undefined;

type CatalogEntry = Pick<Product, 'id' | 'name' | 'price'> & {
  pagePath: ProductPagePath;
  categoryPath: CategoryPagePath;
  categoryName: string;
};

const buildCatalog = (items: readonly Product[]): readonly CatalogEntry[] =>
  items
    .map((item) => {
      const slug = toCategorySlug(item.categoryId);

      if (slug === undefined) {
        return undefined; // カテゴリが特定できない商品は除外する
      }

      return {
        id: item.id,
        name: item.name,
        price: item.price,
        pagePath: toProductPath(item.id),
        categoryPath: toCategoryPath(slug),
        categoryName: CATEGORY_NAME_BY_SLUG[slug],
      };
    })
    .filter((entry): entry is CatalogEntry => entry !== undefined);

type CatalogRow = ElementType<ReturnType<typeof buildCatalog>>;

const formatRow = (row: CatalogRow): string =>
  `${row.id}: ${row.name} / ${row.price}円 / ${row.pagePath} / ${row.categoryPath} / ${row.categoryName}`;

const rawProducts: readonly Product[] = [
  ...products,
  {
    id: 99,
    name: '不正なデータ',
    price: 100,
    stock: 1,
    categoryId: 9,
    description: '外部から来た壊れたデータ。',
    imageUrl: '/img/broken.jpg',
  },
];

function solveQ6(): string {
  const stringified = toStringified(mug);

  const myPartial: MyPartial<Product> = { price: 2500 };
  const builtInPartial: Partial<Product> = myPartial;
  const backAgain: MyPartial<Product> = builtInPartial;

  const readonlyMug: MyReadonly<Product> = { ...mug };
  const editableMug: Mutable<MyReadonly<Product>> = { ...readonlyMug };
  const beforePrice = editableMug.price;
  editableMug.price = 2500;

  const catalog = buildCatalog(rawProducts);

  const lines: string[] = [
    `文字列化: id=${stringified.id} / name=${stringified.name} / price=${stringified.price} / ` +
      `stock=${stringified.stock} / categoryId=${stringified.categoryId}`,
    `編集前: ${beforePrice}円 → 編集後: ${editableMug.price}円`,
  ];

  // MyPartial と Partial が相互に代入できていることの裏付け
  checkNumber('問題6: MyPartial と Partial は相互に代入できる', backAgain.price ?? 0, 2500);

  for (const row of catalog) {
    lines.push(formatRow(row));
  }

  lines.push(
    `取り込み: ${rawProducts.length}件中${catalog.length}件（除外${
      rawProducts.length - catalog.length
    }件）`
  );

  return lines.join('\n');
}

checkString(
  '問題6: 出力8行',
  solveQ6(),
  '文字列化: id=3 / name=マグカップ / price=2350 / stock=3 / categoryId=2\n' +
    '編集前: 2350円 → 編集後: 2500円\n' +
    '1: ラベンダーの石けん / 480円 / /products/1 / /categories/bath-body / バス・ボディケア\n' +
    '2: ハンドクリーム / 1800円 / /products/2 / /categories/bath-body / バス・ボディケア\n' +
    '3: マグカップ / 2350円 / /products/3 / /categories/kitchen / キッチン雑貨\n' +
    '4: リネンのふきん / 990円 / /products/4 / /categories/fabric / ファブリック\n' +
    '5: コットンのトートバッグ / 2800円 / /products/5 / /categories/fabric / ファブリック\n' +
    '取り込み: 6件中5件（除外1件）'
);

// Stringify は「型を変える」だけで「値を変える」わけではない（変換は自分で書く）
checkString('問題6: 文字列化された price', toStringified(mug).price, '2350');
checkNumber('問題6: 元の price は数値のまま', mug.price, 2350);

// 型ガードの挙動（判定の根拠は一覧そのものに置く）
checkBoolean('問題6: categoryId=2 は CategoryId', isCategoryId(2), true);
checkBoolean('問題6: categoryId=9 は CategoryId ではない', isCategoryId(9), false);
checkBoolean('問題6: 壊れたデータは slug を特定できない', toCategorySlug(9) === undefined, true);
checkString('問題6: categoryId=3 の slug', toCategorySlug(3) ?? '(なし)', 'fabric');

// パスを組み立てる関数
checkString('問題6: toImagePath', toImagePath('mug'), '/images/products/mug.png');
checkString('問題6: toCategoryPath', toCategoryPath('bath-body'), '/categories/bath-body');
checkString('問題6: toProductPath', toProductPath(3), '/products/3');

// ---------------------------------------------------------------------------
// 型の主張（ここから下は実行時の意味を持たない。tsc --noEmit が検証する）
//
// ・正しい型であること   … const 変数に代入できることで示す
// ・誤りが弾かれること   … // @ts-expect-error の次の行
//   （エラーが出なくなると @ts-expect-error 自体がエラーになる）
// ---------------------------------------------------------------------------

// --- 1節：型の位置の typeof とインデックスアクセス型 ---
const typeCheckStatus: OrderStatus = 'paid';
// @ts-expect-error 'refunded' は OrderStatus に含まれない（TS2322）
const typeCheckStatusNg: OrderStatus = 'refunded';

const typeCheckFirstStatus: (typeof ORDER_STATUSES)[0] = 'pending';
// @ts-expect-error [0] は 'pending' だけを表す（TS2322）
const typeCheckFirstStatusNg: (typeof ORDER_STATUSES)[0] = 'paid';

const typeCheckPrice: Product['price'] = 2350;
// @ts-expect-error price は number（TS2322）
const typeCheckPriceNg: Product['price'] = '2350';

// @ts-expect-error 'nmae' は Product のキーではない（TS2536）
type TypeCheckTypoIndex = Product['nmae'];

// [number] と infer で作った型は同じもの（相互に代入できる）
const typeCheckStatusViaInfer: ElementType<typeof ORDER_STATUSES> = 'shipped';
const typeCheckStatusViaIndex: OrderStatus = typeCheckStatusViaInfer;
const typeCheckStatusBack: ElementType<typeof ORDER_STATUSES> = typeCheckStatusViaIndex;

// --- 2節：Pick と Omit ---
type ProductInputManual = {
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

// Omit<Product, 'id'> と手書きの6フィールドは同じ型（双方向に代入できる）
const typeCheckInputForward: ProductInputManual = bathSaltInput;
const typeCheckInputBackward: ProductInput = typeCheckInputForward;

// ProductInput のキーに 'id' は含まれない（Omit で除いたため）
const typeCheckInputKey: keyof ProductInput = 'name';
// @ts-expect-error 'id' は keyof ProductInput に含まれない（TS2322）
const typeCheckInputKeyNg: keyof ProductInput = 'id';

const typeCheckSummary: ProductSummary = { id: 3, name: 'マグカップ', price: 2350 };
// @ts-expect-error name と price が足りない（TS2739）
const typeCheckSummaryNg: ProductSummary = { id: 3 };

// @ts-expect-error 'nmae' は keyof Product を満たさない（TS2344）
type TypeCheckPickTypo = Pick<Product, 'nmae'>;

// --- 2節（続き）：Partial / Required / Readonly ---
// Partial<Product> は空オブジェクトも通る（これが罠。エラーにならないことが主張）
const typeCheckEmptyPartial: Partial<Product> = {};

const typeCheckPatch: ProductPatch = { id: 3, price: 2500 };
// @ts-expect-error id が無いので ProductPatch を満たさない（TS2741）
const typeCheckPatchNg: ProductPatch = { price: 2500 };

// Pick で選んだ型は空オブジェクトを許さない（Partial との違い）
// @ts-expect-error price と stock が必要（TS2739）
const typeCheckPickedPatchNg: Pick<Product, 'price' | 'stock'> = {};

const typeCheckReadonly: Readonly<Product> = { ...mug };
// @ts-expect-error readonly なので書き換えられない（TS2540）
typeCheckReadonly.price = 100;

type ProductNote = { readonly productId: number; memo?: string };
const typeCheckRequiredNote: Required<ProductNote> = { productId: 3, memo: 'ギフト包装' };
// @ts-expect-error Required で ? が外れるので memo は省略できない（TS2741）
const typeCheckRequiredNoteNg: Required<ProductNote> = { productId: 3 };

// --- 3節：Record ---
// Record<有限のユニオン, V> は読み出しに undefined が付かない
const typeCheckRankValue: number = DISCOUNT_PERCENT_BY_RANK.gold;

// @ts-expect-error none が足りない（TS2741）
const typeCheckRankTableNg: Record<MemberRank, number> = { gold: 10, silver: 5, bronze: 3 };

// Record<string, V> は index signature なので noUncheckedIndexedAccess で undefined が付く
const typeCheckLooseTable: Record<string, number> = { gold: 10 };
// @ts-expect-error 型は number | undefined になる（TS2322）
const typeCheckLooseValue: number = typeCheckLooseTable['gold'];

// --- 4節：ReturnType / Parameters / Awaited ---
type PaymentSummaryManual = {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
};

// ReturnType で導出した型と、S11 で手書きした7フィールドは同じ型
const typeCheckSummaryForward: PaymentSummaryManual = goldSummary;
const typeCheckSummaryBackward: PaymentSummary = typeCheckSummaryForward;

const typeCheckArgs: Parameters<typeof calcLineTotal> = [480, 2];
// @ts-expect-error 引数は2つ必要なタプル型（TS2741）
const typeCheckArgsNg: Parameters<typeof calcLineTotal> = [480];

const typeCheckRuleArg: RuleArg = makePercentDiscount(10);
// @ts-expect-error 割引ルールは (subtotal: number) => number（TS2322）
const typeCheckRuleArgNg: RuleArg = 10;

const typeCheckAwaited: Awaited<Promise<Product>> = mug;
// @ts-expect-error Awaited で剥がした中身は Product（TS2322）
const typeCheckAwaitedNg: Awaited<Promise<Product>> = 'マグカップ';

// @ts-expect-error 値を型の位置で使っている。typeof が必要（TS2749）
type TypeCheckWrongReturnType = ReturnType<buildPaymentSummary>;

// --- 5節：mapped type ---
const typeCheckMyPartial: MyPartial<Product> = { price: 2500 };
const typeCheckMyPartialForward: Partial<Product> = typeCheckMyPartial;
const typeCheckMyPartialBackward: MyPartial<Product> = typeCheckMyPartialForward;

const typeCheckMyReadonly: MyReadonly<Product> = { ...mug };
// @ts-expect-error 自作の MyReadonly でも readonly は効く（TS2540）
typeCheckMyReadonly.price = 100;

const typeCheckMutable: Mutable<MyReadonly<Product>> = { ...mug };
typeCheckMutable.price = 2500; // -readonly で外したので通る

const typeCheckConcrete: Concrete<ProductNote> = { productId: 3, memo: 'ギフト包装' };
// @ts-expect-error -? で ? を外したので memo は省略できない（TS2741）
const typeCheckConcreteNg: Concrete<ProductNote> = { productId: 3 };

const typeCheckStringified: Stringify<Product> = toStringified(mug);
// @ts-expect-error Stringify では price も string になる（TS2322）
typeCheckStringified.price = 2350;

// --- 6節：条件型と infer ---
const typeCheckElement: ElementType<typeof products> = mug;
// @ts-expect-error 要素の型は Product（TS2322）
const typeCheckElementNg: ElementType<typeof products> = 'マグカップ';

// 配列ではない型を渡すと never になる（何も代入できない）
// @ts-expect-error ElementType<number> は never（TS2322）
const typeCheckElementNever: ElementType<number> = 480;

// --- 7節：テンプレートリテラル型 ---
const typeCheckImagePath: ProductImagePath = '/images/products/mug.png';
// @ts-expect-error 拡張子が .png ではない（TS2322）
const typeCheckImagePathNgExt: ProductImagePath = '/images/products/mug.jpg';
// @ts-expect-error ディレクトリが違う（TS2322）
const typeCheckImagePathNgDir: ProductImagePath = '/img/mug.png';

const typeCheckCategoryPath: CategoryPagePath = '/categories/kitchen';
// @ts-expect-error 'sale' は CategorySlug に含まれない（TS2322）
const typeCheckCategoryPathNg: CategoryPagePath = '/categories/sale';

const typeCheckProductPath: ProductPagePath = '/products/3';
// @ts-expect-error /product/ は単数形（TS2322）
const typeCheckProductPathNg: ProductPagePath = '/product/3';

// 組み立て関数の戻り値も、テンプレートリテラル型として検査される
const typeCheckGeneratedImage: ProductImagePath = toImagePath('mug');
const typeCheckGeneratedCategory: CategoryPagePath = toCategoryPath('kitchen');
const typeCheckGeneratedProduct: ProductPagePath = toProductPath(3);

// --- 問題6：一覧から作った数値のユニオン型 ---
const typeCheckCategoryId: CategoryId = 2;
// @ts-expect-error 9 は CategoryId（1 | 2 | 3）に含まれない（TS2322）
const typeCheckCategoryIdNg: CategoryId = 9;

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session14: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session14: ok');
