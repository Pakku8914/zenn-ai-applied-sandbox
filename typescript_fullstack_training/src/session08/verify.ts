/**
 * セッション8「オブジェクトとオブジェクト型」の検証スクリプト。
 *
 * 本文（023）と練習問題の解答（025）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * console.log を1行ずつ出す章のコードは、この検証では
 * 「出力行を \n でつないだ文字列」を返す関数として表現している。
 *
 * 実行: docker compose exec ts npx tsx src/session08/verify.ts
 */

import { inspect } from 'node:util';

// ---------------------------------------------------------------------------
// 共通の定数（本書は金額を整数の円で扱う）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;

const DEFAULT_DESCRIPTION = '（説明は準備中です）';
const DEFAULT_IMAGE_URL = '/images/products/no-image.png';

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
// 本文で共通に使う商品マスタ（本文7節 src/session08/products.ts と同じ）
// ---------------------------------------------------------------------------
const categories: { readonly id: number; name: string; slug: string }[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const products = [
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
// 本文 1節：オブジェクトリテラル（src/session08/product-object.ts）
// ---------------------------------------------------------------------------
function buildProductObjectOutput(): string {
  const soap = {
    id: 1,
    name: 'ラベンダーの石けん',
    price: 480,
    stock: 24,
  };

  const lines: string[] = [];
  lines.push(soap.name);
  lines.push(String(soap.price));
  lines.push(`${soap.name}：${soap.price}円（在庫${soap.stock}点）`);
  lines.push(inspect({ id: 1, name: 'ラベンダーの石けん' }));

  // 1点売れたので在庫を減らす（const はプロパティの書き換えを禁止しない）
  soap.stock = soap.stock - 1;
  lines.push(String(soap.stock));

  // 省略記法
  const name = 'ハンドクリーム';
  const price = 1800;
  const cream = { name, price };
  lines.push(`${cream.name}：${cream.price}円`);

  return lines.join('\n');
}

checkString(
  '本文1節: オブジェクトリテラルの出力',
  buildProductObjectOutput(),
  'ラベンダーの石けん\n' +
    '480\n' +
    'ラベンダーの石けん：480円（在庫24点）\n' +
    "{ id: 1, name: 'ラベンダーの石けん' }\n" +
    '23\n' +
    'ハンドクリーム：1800円'
);

// ---------------------------------------------------------------------------
// 本文 2節：オブジェクト型の型注釈（src/session08/object-type.ts）
// ---------------------------------------------------------------------------
const bodyMug: { id: number; name: string; price: number; stock: number } = {
  id: 3,
  name: 'マグカップ',
  price: 2350,
  stock: 3,
};

/** 必要なプロパティだけを型に書く（構造的部分型） */
function describeProduct(product: { name: string; price: number }): string {
  return `${product.name}：${product.price}円`;
}

checkString('本文2節: describeProduct(mug)', describeProduct(bodyMug), 'マグカップ：2350円');
// id や stock を持つオブジェクトでも、必要なプロパティが揃っていれば渡せる
checkString(
  '本文2節: 商品マスタの要素も渡せる',
  describeProduct({ name: products[0]?.name ?? '', price: products[0]?.price ?? 0 }),
  'ラベンダーの石けん：480円'
);

// ---------------------------------------------------------------------------
// 本文 3節：ドット記法とブラケット記法（src/session08/dot-bracket.ts）
// ---------------------------------------------------------------------------
function buildDotBracketOutput(): string {
  const soap = { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24 };

  const lines: string[] = [];
  lines.push(soap.name);
  lines.push(soap['name']);

  // 型注釈を付けない定数はリテラル型に推論されるので、ブラケット記法で使える
  const targetKey = 'price';
  lines.push(String(soap[targetKey]));

  const shippingFlags = { 'free-shipping': true, 'gift-wrap': false };
  lines.push(String(shippingFlags['free-shipping']));

  return lines.join('\n');
}

checkString(
  '本文3節: ドット記法とブラケット記法',
  buildDotBracketOutput(),
  'ラベンダーの石けん\nラベンダーの石けん\n480\ntrue'
);

// ---------------------------------------------------------------------------
// 本文 4節：オプショナルプロパティと readonly（src/session08/optional-readonly.ts）
// ---------------------------------------------------------------------------
function buildOptionalReadonlyOutput(): string {
  const towel: {
    id: number;
    name: string;
    price: number;
    stock: number;
    description?: string;
    imageUrl?: string;
  } = {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
  };

  const lines: string[] = [];
  lines.push(String(towel.description));
  lines.push(towel.description ?? DEFAULT_DESCRIPTION);
  lines.push(towel.imageUrl ?? DEFAULT_IMAGE_URL);

  const category: { readonly id: number; name: string; slug: string } = {
    id: 1,
    name: 'バス・ボディケア',
    slug: 'bath-body',
  };

  // name は書き換えられる（id は readonly なので代入すると型エラーになる）
  category.name = 'バス＆ボディケア';
  lines.push(`${category.name}（${category.slug}）`);

  return lines.join('\n');
}

checkString(
  '本文4節: オプショナルプロパティと readonly',
  buildOptionalReadonlyOutput(),
  'undefined\n（説明は準備中です）\n/images/products/no-image.png\nバス＆ボディケア（bath-body）'
);

// 「省略した場合」と「空文字を入れた場合」は別物であることの確認
const towelWithEmptyDescription: { name: string; description?: string } = {
  name: 'リネンのふきん',
  description: '',
};
checkString(
  '本文4節: 空文字には既定値が使われない',
  towelWithEmptyDescription.description ?? DEFAULT_DESCRIPTION,
  ''
);

// ---------------------------------------------------------------------------
// 本文 5節：分割代入（src/session08/destructuring.ts / bad-many-args.ts）
// ---------------------------------------------------------------------------

/** Bad: 引数を並べる書き方。price と stock を逆に渡しても型エラーにならない */
function buildProductLabelByArgs(
  name: string,
  price: number,
  stock: number,
  categoryId: number
): string {
  const stockLabel = stock > 0 ? `在庫${stock}点` : '在庫切れ';
  return `${name} ${price}円（${stockLabel}）[${categoryId}]`;
}

/** Good: オブジェクト1つを受け取り、分割代入で取り出す */
function buildProductLabel(product: { name: string; price: number; stock: number }): string {
  const { name: labelName, price: labelPrice, stock } = product;
  const stockLabel = stock > 0 ? `在庫${stock}点` : '在庫切れ';
  return `${labelName} ${labelPrice}円（${stockLabel}）`;
}

function buildDestructuringOutput(): string {
  const mug = { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 };

  const lines: string[] = [];

  const { name, price } = mug;
  lines.push(`${name} / ${price}円`);

  const { name: productName } = mug;
  lines.push(productName);

  const towel: { name: string; price: number; description?: string } = {
    name: 'リネンのふきん',
    price: 990,
  };
  const { description = DEFAULT_DESCRIPTION } = towel;
  lines.push(description);

  lines.push(buildProductLabel(mug));

  // 配列の分割代入（デフォルト値で undefined を消す）
  const prices: number[] = [480, 1800, 2350];
  const [firstPrice = 0, secondPrice = 0] = prices;
  lines.push(`1番目: ${firstPrice}円 / 2番目: ${secondPrice}円`);

  // タプルの分割代入（デフォルト値は不要）
  const nameAndPrice: [string, number] = ['マグカップ', 2350];
  const [tupleName, tuplePrice] = nameAndPrice;
  lines.push(`${tupleName}は${tuplePrice}円`);

  // rest 記法
  const [head = 0, ...restPrices] = prices;
  lines.push(`${head} / ${restPrices.length}`);

  const { id, ...withoutId } = mug;
  lines.push(`${id} / ${withoutId.name}`);

  return lines.join('\n');
}

checkString(
  '本文5節: 分割代入の出力',
  buildDestructuringOutput(),
  'マグカップ / 2350円\n' +
    'マグカップ\n' +
    '（説明は準備中です）\n' +
    'マグカップ 2350円（在庫3点）\n' +
    '1番目: 480円 / 2番目: 1800円\n' +
    'マグカップは2350円\n' +
    '480 / 2\n' +
    '3 / マグカップ'
);
checkString(
  '本文5節 Bad: 引数の順番を間違えても動いてしまう',
  buildProductLabelByArgs('マグカップ', 3, 2350, 2),
  'マグカップ 3円（在庫2350点）[2]'
);
checkString(
  '本文5節 Good: オブジェクトを渡せば順番を間違えない',
  buildProductLabel(bodyMug),
  'マグカップ 2350円（在庫3点）'
);

// ---------------------------------------------------------------------------
// 本文 6節：スプレッド構文（src/session08/spread.ts）
// ---------------------------------------------------------------------------
const PRODUCT_DEFAULTS = {
  stock: 0,
  description: DEFAULT_DESCRIPTION,
  imageUrl: DEFAULT_IMAGE_URL,
};

function buildSpreadOutput(): string {
  const soap = { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24 };
  const restocked = { ...soap, stock: soap.stock + 12 };

  const lines: string[] = [];
  lines.push(`元の在庫: ${soap.stock}点`);
  lines.push(`入荷後の在庫: ${restocked.stock}点`);
  lines.push(`商品名は同じ: ${restocked.name}`);

  const input = { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5 };
  const filled = { ...PRODUCT_DEFAULTS, ...input };
  lines.push(`${filled.name} / 在庫${filled.stock}点 / ${filled.description}`);

  const broken = { ...input, ...PRODUCT_DEFAULTS };
  lines.push(`順番を逆にすると在庫${broken.stock}点`);

  return lines.join('\n');
}

checkString(
  '本文6節: スプレッド構文の出力',
  buildSpreadOutput(),
  '元の在庫: 24点\n' +
    '入荷後の在庫: 36点\n' +
    '商品名は同じ: ラベンダーの石けん\n' +
    'コットンのトートバッグ / 在庫5点 / （説明は準備中です）\n' +
    '順番を逆にすると在庫0点'
);

// キーがあって値が undefined の場合は、既定値ではなく undefined で上書きされる
const overriddenByUndefined = { ...PRODUCT_DEFAULTS, stock: undefined };
checkBoolean(
  '本文6節: undefined でも上書きされる',
  overriddenByUndefined.stock === undefined,
  true
);

// スプレッド構文は浅いコピー（よくある誤解の確認方法）
const mugWithCategory = {
  id: 3,
  name: 'マグカップ',
  price: 2350,
  category: { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
};
const shallowCopy = { ...mugWithCategory };
shallowCopy.category.name = 'キッチン';
checkString('誤解の確認: スプレッドは1階層目だけ', mugWithCategory.category.name, 'キッチン');
// 1階層目は独立している
shallowCopy.name = 'マグ';
checkString('誤解の確認: 1階層目は独立している', mugWithCategory.name, 'マグカップ');
// 元に戻す（後続の検証に影響させない）
mugWithCategory.category.name = 'キッチン雑貨';

// ---------------------------------------------------------------------------
// 本文 7節：オブジェクトの配列とネスト（src/session08/products.ts）
// ---------------------------------------------------------------------------
function buildProductListOutput(
  productList: { name: string; price: number; stock: number }[]
): string {
  const lines: string[] = [];
  for (const product of productList) {
    const stockLabel = product.stock > 0 ? `在庫${product.stock}点` : '在庫切れ';
    lines.push(`${product.name}：${product.price}円（${stockLabel}）`);
  }
  return lines.join('\n');
}

/** id から商品名を返す。見つからなければ案内文を返す */
function findProductNameById(productList: { id: number; name: string }[], id: number): string {
  for (const product of productList) {
    if (product.id === id) {
      return product.name;
    }
  }
  return '(該当する商品がありません)';
}

checkString(
  '本文7節: 商品一覧の出力',
  buildProductListOutput(products),
  'ラベンダーの石けん：480円（在庫24点）\n' +
    'ハンドクリーム：1800円（在庫12点）\n' +
    'マグカップ：2350円（在庫3点）\n' +
    'リネンのふきん：990円（在庫切れ）\n' +
    'コットンのトートバッグ：2800円（在庫5点）'
);
checkString('本文7節: id=3 の商品名', findProductNameById(products, 3), 'マグカップ');
checkString(
  '本文7節: 見つからない場合',
  findProductNameById(products, 99),
  '(該当する商品がありません)'
);
checkString('本文7節: ネストしたオブジェクト', mugWithCategory.category.name, 'キッチン雑貨');
checkString(
  '本文7節: ネストを辿って組み立てる',
  `${mugWithCategory.name} / ${mugWithCategory.category.slug}`,
  'マグカップ / kitchen'
);

// 本文7節の Product は requirements.md の固定エンティティどおりのフィールドを持つ
const firstProduct = products[0];
checkBoolean('本文7節: description を持つ', (firstProduct?.description ?? '') !== '', true);
checkBoolean('本文7節: imageUrl を持つ', (firstProduct?.imageUrl ?? '') !== '', true);
checkNumber('本文7節: categoryId を持つ', firstProduct?.categoryId ?? 0, 1);

// ---------------------------------------------------------------------------
// 本文 8節：インデックスシグネチャ（src/session08/stock-by-category.ts）
// ---------------------------------------------------------------------------
function buildStockAmountByCategoryOutput(
  categoryList: { readonly id: number; name: string; slug: string }[],
  productList: { price: number; stock: number; categoryId: number }[]
): string {
  const categoryNameById: { [key: number]: string } = {};
  for (const category of categoryList) {
    categoryNameById[category.id] = category.name;
  }

  const stockAmountByCategory: { [key: string]: number } = {};
  for (const product of productList) {
    const categoryName = categoryNameById[product.categoryId] ?? '(未分類)';
    const current = stockAmountByCategory[categoryName] ?? 0;
    stockAmountByCategory[categoryName] = current + product.price * product.stock;
  }

  const lines: string[] = [];
  for (const category of categoryList) {
    const amount = stockAmountByCategory[category.name] ?? 0;
    lines.push(`${category.name}：在庫金額 ${amount}円`);
  }
  return lines.join('\n');
}

checkString(
  '本文8節: カテゴリ別の在庫金額',
  buildStockAmountByCategoryOutput(categories, products),
  'バス・ボディケア：在庫金額 33120円\n' +
    'キッチン雑貨：在庫金額 7050円\n' +
    'ファブリック：在庫金額 14000円'
);

// Bad/Good の確認：タイポしたキーは undefined になる
const stockByName: { [key: string]: number } = { 'マグカップ': 3 };
// 章の Bad 例（型エラーを無視して実行した状態）を再現するため、ここだけ型アサーションを使う
const missingStock = stockByName['マグカッブ'] as number;
checkBoolean('本文8節 Bad: タイポしたキーで計算すると NaN', Number.isNaN(missingStock + 1), true);
checkNumber('本文8節 Good: ?? 0 を付ければ 1 になる', (stockByName['マグカッブ'] ?? 0) + 1, 1);
checkNumber('本文8節: 正しいキーなら値が取れる', stockByName['マグカップ'] ?? 0, 3);

// よくあるエラーの確認：範囲外の要素のプロパティを読むと実行時エラーになる
function readNameUnsafely(list: { name: string }[], index: number): string {
  // 章の「よくあるエラー」を再現するため、意図的に undefined チェックを飛ばす
  const item = list[index] as { name: string };
  return item.name;
}

let caughtMessage = '';
try {
  readNameUnsafely(products, 9);
} catch (error) {
  caughtMessage = String(error);
}
checkBoolean(
  'よくあるエラー: 範囲外の要素は TypeError になる',
  caughtMessage.includes("Cannot read properties of undefined (reading 'name')"),
  true
);

// ---------------------------------------------------------------------------
// 本文 9節：カートの支払明細（src/session08/cart-total.ts）
// ---------------------------------------------------------------------------
function calcLineTotal(price: number, quantity: number): number {
  return price * quantity;
}

function calcSubtotal(items: { product: { price: number }; quantity: number }[]): number {
  let subtotal = 0;
  for (const item of items) {
    subtotal += calcLineTotal(item.product.price, item.quantity);
  }
  return subtotal;
}

function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

function calcPayableAmount(subtotal: number, rule: (subtotal: number) => number): number {
  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  return totalWithTax + calcShippingFee(totalWithTax);
}

/** 支払総額の内訳をひとまとまりで返す（本文9節） */
function buildPaymentSummaryFromItems(
  items: { product: { price: number }; quantity: number }[],
  rule: (subtotal: number) => number
): {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
} {
  const subtotal = calcSubtotal(items); // 手順1
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
}

const silverRule = (subtotal: number): number => Math.floor((subtotal * 5) / 100);

function buildCartTotalOutput(): string {
  const soap = { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24 };
  const mug = { id: 3, name: 'マグカップ', price: 2350, stock: 3 };

  const cartItems = [
    { product: soap, quantity: 2 },
    { product: mug, quantity: 1 },
  ];

  const lines: string[] = [];
  for (const { product, quantity } of cartItems) {
    const lineTotal = calcLineTotal(product.price, quantity);
    lines.push(`${product.name} ${product.price}円 × ${quantity}点 = ${lineTotal}円`);
  }

  const {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount,
  } = buildPaymentSummaryFromItems(cartItems, silverRule);

  lines.push(`小計: ${subtotal}円`);
  lines.push(`割引額: ${discountAmount}円`);
  lines.push(`割引後小計: ${discountedTotal}円`);
  lines.push(`消費税: ${tax}円`);
  lines.push(`税込商品合計: ${totalWithTax}円`);
  lines.push(`送料: ${shippingFee}円`);
  lines.push(`お支払い金額: ${payableAmount}円`);

  // 確定シグネチャの calcPayableAmount と同じ結果になることを確認する
  checkNumber(
    '本文9節: calcPayableAmount と一致する',
    calcPayableAmount(subtotal, silverRule),
    payableAmount
  );

  return lines.join('\n');
}

checkString(
  '本文9節: カートの支払明細',
  buildCartTotalOutput(),
  'ラベンダーの石けん 480円 × 2点 = 960円\n' +
    'マグカップ 2350円 × 1点 = 2350円\n' +
    '小計: 3310円\n' +
    '割引額: 165円\n' +
    '割引後小計: 3145円\n' +
    '消費税: 314円\n' +
    '税込商品合計: 3459円\n' +
    '送料: 0円\n' +
    'お支払い金額: 3459円'
);

// 計算手順を1つずつ検算する（requirements.md の正典どおりであること）
checkNumber('本文9節: 手順1 小計', 480 * 2 + 2350 * 1, 3310);
checkNumber('本文9節: 手順2 割引額', Math.floor((3310 * 5) / 100), 165);
checkNumber('本文9節: 手順3 割引後小計', 3310 - 165, 3145);
checkNumber('本文9節: 手順4 消費税', Math.floor(3145 * TAX_RATE), 314);
checkNumber('本文9節: 手順5 税込商品合計', 3145 + 314, 3459);
checkNumber('本文9節: 手順6 送料', calcShippingFee(3459), 0);

// ---------------------------------------------------------------------------
// 問題1：商品オブジェクトを作って読む
// ---------------------------------------------------------------------------
function buildQ1Output(): string {
  const cream: {
    id: number;
    name: string;
    price: number;
    stock: number;
    description: string;
    imageUrl: string;
    categoryId: number;
  } = {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    stock: 12,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png',
    categoryId: 1,
  };

  const lines: string[] = [];
  lines.push(`商品名: ${cream.name}`);
  lines.push(`価格: ${cream.price}円`);
  lines.push(`在庫: ${cream.stock}点`);
  lines.push(`説明: ${cream.description}`);
  lines.push(`画像: ${cream.imageUrl}`);
  lines.push(`カテゴリID: ${cream.categoryId}`);
  lines.push(`ブラケット記法で読んだ商品名: ${cream['name']}`);

  cream.stock = cream.stock - 1;
  lines.push(`1点売れたあとの在庫: ${cream.stock}点`);

  return lines.join('\n');
}

checkString(
  '問題1: 出力8行',
  buildQ1Output(),
  '商品名: ハンドクリーム\n' +
    '価格: 1800円\n' +
    '在庫: 12点\n' +
    '説明: べたつかない使用感の保湿ハンドクリームです。\n' +
    '画像: /images/products/hand-cream.png\n' +
    'カテゴリID: 1\n' +
    'ブラケット記法で読んだ商品名: ハンドクリーム\n' +
    '1点売れたあとの在庫: 11点'
);

// ---------------------------------------------------------------------------
// 問題2：オプショナルプロパティと readonly
// ---------------------------------------------------------------------------
function buildQ2Output(): string {
  const cream: {
    id: number;
    name: string;
    price: number;
    stock: number;
    description?: string;
    imageUrl?: string;
  } = {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    stock: 12,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png',
  };

  const cloth: {
    id: number;
    name: string;
    price: number;
    stock: number;
    description?: string;
    imageUrl?: string;
  } = {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
  };

  const lines: string[] = [];
  lines.push(`${cream.name} の説明: ${cream.description ?? DEFAULT_DESCRIPTION}`);
  lines.push(`${cream.name} の画像: ${cream.imageUrl ?? DEFAULT_IMAGE_URL}`);
  lines.push(`${cloth.name} の説明: ${cloth.description ?? DEFAULT_DESCRIPTION}`);
  lines.push(`${cloth.name} の画像: ${cloth.imageUrl ?? DEFAULT_IMAGE_URL}`);

  const category: { readonly id: number; name: string; slug: string } = {
    id: 1,
    name: 'バス・ボディケア',
    slug: 'bath-body',
  };
  category.name = 'バス＆ボディケア';
  lines.push(`カテゴリ名を変更しました: ${category.name}（${category.slug}）`);

  return lines.join('\n');
}

checkString(
  '問題2: 出力5行',
  buildQ2Output(),
  'ハンドクリーム の説明: べたつかない使用感の保湿ハンドクリームです。\n' +
    'ハンドクリーム の画像: /images/products/hand-cream.png\n' +
    'リネンのふきん の説明: （説明は準備中です）\n' +
    'リネンのふきん の画像: /images/products/no-image.png\n' +
    'カテゴリ名を変更しました: バス＆ボディケア（bath-body）'
);

// ---------------------------------------------------------------------------
// 問題3：分割代入
// ---------------------------------------------------------------------------
function buildLabelFromParams({
  name,
  price,
  stock,
}: {
  name: string;
  price: number;
  stock: number;
}): string {
  const stockLabel = stock > 0 ? `在庫${stock}点` : '在庫切れ';
  return `${name} ${price}円（${stockLabel}）`;
}

function buildQ3Output(): string {
  const mug = { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 };

  const lines: string[] = [];

  const { name, price } = mug;
  lines.push(`${name} / ${price}円`);

  const { name: productName } = mug;
  lines.push(`リネーム後: ${productName}`);

  const cloth: {
    id: number;
    name: string;
    price: number;
    stock: number;
    description?: string;
  } = {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
  };
  const { description = DEFAULT_DESCRIPTION } = cloth;
  lines.push(`${cloth.name} の説明: ${description}`);

  lines.push(`ラベル: ${buildLabelFromParams(mug)}`);
  lines.push(`ラベル: ${buildLabelFromParams(cloth)}`);

  const prices: number[] = [480, 1800, 2350];
  const [firstPrice = 0, secondPrice = 0] = prices;
  lines.push(`配列から: 1番目 ${firstPrice}円 / 2番目 ${secondPrice}円`);

  const nameAndPrice: [string, number] = ['コットンのトートバッグ', 2800];
  const [tupleName, tuplePrice] = nameAndPrice;
  lines.push(`タプルから: ${tupleName} / ${tuplePrice}円`);

  return lines.join('\n');
}

checkString(
  '問題3: 出力7行',
  buildQ3Output(),
  'マグカップ / 2350円\n' +
    'リネーム後: マグカップ\n' +
    'リネンのふきん の説明: （説明は準備中です）\n' +
    'ラベル: マグカップ 2350円（在庫3点）\n' +
    'ラベル: リネンのふきん 990円（在庫切れ）\n' +
    '配列から: 1番目 480円 / 2番目 1800円\n' +
    'タプルから: コットンのトートバッグ / 2800円'
);

// ---------------------------------------------------------------------------
// 問題4：スプレッド構文
// ---------------------------------------------------------------------------
function applyRestock(
  product: { id: number; name: string; price: number; stock: number },
  amount: number
): { id: number; name: string; price: number; stock: number } {
  return { ...product, stock: product.stock + amount };
}

function applyPrice(
  product: { id: number; name: string; price: number; stock: number },
  price: number
): { id: number; name: string; price: number; stock: number } {
  return { ...product, price };
}

function withDefaults(input: {
  id: number;
  name: string;
  price: number;
  stock?: number;
  description?: string;
  imageUrl?: string;
}) {
  return { ...PRODUCT_DEFAULTS, ...input };
}

function buildQ4Output(): string {
  const soap = { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24 };

  const lines: string[] = [];
  lines.push(`元の在庫: ${soap.stock}点`);

  const restocked = applyRestock(soap, 12);
  lines.push(`入荷後の在庫: ${restocked.stock}点`);
  lines.push(`元の在庫は変わらない: ${soap.stock}点`);

  const discounted = applyPrice(soap, 380);
  lines.push(`値下げ後: ${discounted.name} ${discounted.price}円`);
  lines.push(`元の価格は変わらない: ${soap.price}円`);

  const input = { id: 5, name: 'コットンのトートバッグ', price: 2800 };
  const filled = withDefaults(input);
  lines.push(`既定値で補完: ${filled.name} / 在庫${filled.stock}点 / ${filled.description}`);

  const inputWithStock = { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5 };
  const filled2 = withDefaults(inputWithStock);
  lines.push(`入力を優先: ${filled2.name} / 在庫${filled2.stock}点 / ${filled2.description}`);

  const wrongOrder = { ...inputWithStock, ...PRODUCT_DEFAULTS };
  lines.push(`順番を逆にすると: 在庫${wrongOrder.stock}点`);

  return lines.join('\n');
}

checkString(
  '問題4: 出力8行',
  buildQ4Output(),
  '元の在庫: 24点\n' +
    '入荷後の在庫: 36点\n' +
    '元の在庫は変わらない: 24点\n' +
    '値下げ後: ラベンダーの石けん 380円\n' +
    '元の価格は変わらない: 480円\n' +
    '既定値で補完: コットンのトートバッグ / 在庫0点 / （説明は準備中です）\n' +
    '入力を優先: コットンのトートバッグ / 在庫5点 / （説明は準備中です）\n' +
    '順番を逆にすると: 在庫0点'
);

// ---------------------------------------------------------------------------
// 問題5：商品の配列を集計する
// ---------------------------------------------------------------------------
const q5Products = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

function buildQ5Output(
  productList: { id: number; name: string; price: number; stock: number }[]
): string {
  const lines: string[] = [];

  for (const product of productList) {
    const stockLabel = product.stock > 0 ? `在庫${product.stock}点` : '在庫切れ';
    lines.push(`${product.name}：${product.price}円（${stockLabel}）`);
  }

  let inStockCount = 0;
  let totalStockAmount = 0;
  let mostExpensive = { name: '(商品がありません)', price: 0 };

  for (const product of productList) {
    if (product.stock > 0) {
      inStockCount = inStockCount + 1;
    }
    totalStockAmount = totalStockAmount + product.price * product.stock;
    if (product.price > mostExpensive.price) {
      mostExpensive = { name: product.name, price: product.price };
    }
  }

  lines.push(`在庫のある商品: ${inStockCount}件`);
  lines.push(`在庫金額の合計: ${totalStockAmount}円`);
  lines.push(`一番高い商品: ${mostExpensive.name}（${mostExpensive.price}円）`);
  lines.push(`id=3 の商品名: ${findProductNameById(productList, 3)}`);
  lines.push(`id=99 の商品名: ${findProductNameById(productList, 99)}`);

  return lines.join('\n');
}

checkString(
  '問題5: 出力10行',
  buildQ5Output(q5Products),
  'ラベンダーの石けん：480円（在庫24点）\n' +
    'ハンドクリーム：1800円（在庫12点）\n' +
    'マグカップ：2350円（在庫3点）\n' +
    'リネンのふきん：990円（在庫切れ）\n' +
    'コットンのトートバッグ：2800円（在庫5点）\n' +
    '在庫のある商品: 4件\n' +
    '在庫金額の合計: 54170円\n' +
    '一番高い商品: コットンのトートバッグ（2800円）\n' +
    'id=3 の商品名: マグカップ\n' +
    'id=99 の商品名: (該当する商品がありません)'
);
checkNumber('問題5: 在庫金額の検算', 480 * 24 + 1800 * 12 + 2350 * 3 + 990 * 0 + 2800 * 5, 54170);
// 空のリストでも壊れないこと（設計と運用のポイントで触れた挙動）
checkString(
  '問題5: 空のリストでも案内文になる',
  buildQ5Output([]),
  '在庫のある商品: 0件\n' +
    '在庫金額の合計: 0円\n' +
    '一番高い商品: (商品がありません)（0円）\n' +
    'id=3 の商品名: (該当する商品がありません)\n' +
    'id=99 の商品名: (該当する商品がありません)'
);

// ---------------------------------------------------------------------------
// 問題6：インデックスシグネチャでカテゴリ別に集計する
// ---------------------------------------------------------------------------
const UNCATEGORIZED = '(未分類)';

function buildQ6Output(): string {
  const q6Products = [
    ...q5Products,
    { id: 6, name: 'ドライフラワーのスワッグ', price: 3000, stock: 1, categoryId: 9 },
  ];

  const categoryNameById: { [key: number]: string } = {};
  for (const category of categories) {
    categoryNameById[category.id] = category.name;
  }

  const countByCategory: { [key: string]: number } = {};
  const stockAmountByCategory: { [key: string]: number } = {};

  for (const product of q6Products) {
    const categoryName = categoryNameById[product.categoryId] ?? UNCATEGORIZED;
    countByCategory[categoryName] = (countByCategory[categoryName] ?? 0) + 1;
    stockAmountByCategory[categoryName] =
      (stockAmountByCategory[categoryName] ?? 0) + product.price * product.stock;
  }

  const lines: string[] = [];
  let totalCount = 0;
  let totalAmount = 0;

  for (const category of categories) {
    const count = countByCategory[category.name] ?? 0;
    const amount = stockAmountByCategory[category.name] ?? 0;
    totalCount = totalCount + count;
    totalAmount = totalAmount + amount;
    lines.push(`${category.name}（${category.slug}）: ${count}件 / 在庫金額 ${amount}円`);
  }

  const uncategorizedCount = countByCategory[UNCATEGORIZED] ?? 0;
  if (uncategorizedCount > 0) {
    const uncategorizedAmount = stockAmountByCategory[UNCATEGORIZED] ?? 0;
    totalCount = totalCount + uncategorizedCount;
    totalAmount = totalAmount + uncategorizedAmount;
    lines.push(`${UNCATEGORIZED}: ${uncategorizedCount}件 / 在庫金額 ${uncategorizedAmount}円`);
  }

  lines.push(`合計: ${totalCount}件 / 在庫金額 ${totalAmount}円`);

  return lines.join('\n');
}

checkString(
  '問題6: 出力5行',
  buildQ6Output(),
  'バス・ボディケア（bath-body）: 2件 / 在庫金額 33120円\n' +
    'キッチン雑貨（kitchen）: 1件 / 在庫金額 7050円\n' +
    'ファブリック（fabric）: 2件 / 在庫金額 14000円\n' +
    '(未分類): 1件 / 在庫金額 3000円\n' +
    '合計: 6件 / 在庫金額 57170円'
);
checkNumber('問題6: バス・ボディケアの検算', 480 * 24 + 1800 * 12, 33120);
checkNumber('問題6: ファブリックの検算', 990 * 0 + 2800 * 5, 14000);
checkNumber('問題6: 合計の検算', 54170 + 3000 * 1, 57170);

// ---------------------------------------------------------------------------
// 問題7：カートの支払明細をひとまとまりで返す
// ---------------------------------------------------------------------------
function adjustQuantity(quantity: number, stock: number): number {
  if (quantity <= 0 || stock <= 0) {
    return 0;
  }
  return Math.min(quantity, stock);
}

function buildCartLines(
  items: { product: { name: string; price: number; stock: number }; quantity: number }[]
): { label: string; lineTotal: number }[] {
  const lines: { label: string; lineTotal: number }[] = [];

  for (const { product, quantity } of items) {
    if (product.stock <= 0) {
      lines.push({ label: `${product.name}: 在庫切れのため注文できません`, lineTotal: 0 });
      continue;
    }

    const orderedQuantity = adjustQuantity(quantity, product.stock);
    const lineTotal = product.price * orderedQuantity;
    const base = `${product.name} ${product.price}円 × ${orderedQuantity}点 = ${lineTotal}円`;

    if (orderedQuantity < quantity) {
      lines.push({
        label: `${base}（注文${quantity}点のうち在庫${product.stock}点まで）`,
        lineTotal,
      });
      continue;
    }

    lines.push({ label: base, lineTotal });
  }

  return lines;
}

function buildPaymentSummary(
  items: { product: { name: string; price: number; stock: number }; quantity: number }[],
  rule: (subtotal: number) => number
): {
  subtotal: number;
  discountAmount: number;
  discountedTotal: number;
  tax: number;
  totalWithTax: number;
  shippingFee: number;
  payableAmount: number;
} {
  let subtotal = 0;
  for (const { lineTotal } of buildCartLines(items)) {
    subtotal = subtotal + lineTotal;
  }

  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);
  const payableAmount = totalWithTax + shippingFee;

  return {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount,
  };
}

function buildCartReport(
  title: string,
  items: { product: { name: string; price: number; stock: number }; quantity: number }[],
  rule: (subtotal: number) => number
): string {
  const lines: string[] = [`--- ${title} ---`];

  for (const { label } of buildCartLines(items)) {
    lines.push(label);
  }

  const {
    subtotal,
    discountAmount,
    discountedTotal,
    tax,
    totalWithTax,
    shippingFee,
    payableAmount,
  } = buildPaymentSummary(items, rule);

  lines.push(`小計: ${subtotal}円`);
  lines.push(`割引額: ${discountAmount}円`);
  lines.push(`割引後小計: ${discountedTotal}円`);
  lines.push(`消費税: ${tax}円`);
  lines.push(`税込商品合計: ${totalWithTax}円`);
  lines.push(`送料: ${shippingFee}円`);
  lines.push(`お支払い金額: ${payableAmount}円`);

  return lines.join('\n');
}

const goldRule = (subtotal: number): number => Math.floor((subtotal * 10) / 100);

const q7Cart1 = [
  { product: { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24 }, quantity: 3 },
  { product: { id: 3, name: 'マグカップ', price: 2350, stock: 3 }, quantity: 5 },
  { product: { id: 4, name: 'リネンのふきん', price: 990, stock: 0 }, quantity: 1 },
];

const q7Cart2 = [
  { product: { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24 }, quantity: 2 },
];

// adjustQuantity の境界（解答の①で示した値）
checkNumber('問題7: 在庫を超える注文は在庫数まで', adjustQuantity(5, 3), 3);
checkNumber('問題7: 在庫内ならそのまま', adjustQuantity(3, 24), 3);
checkNumber('問題7: 負の数量は0', adjustQuantity(-1, 24), 0);
checkNumber('問題7: 在庫0なら0', adjustQuantity(2, 0), 0);

checkString(
  '問題7: カート1の出力',
  buildCartReport('カート1', q7Cart1, goldRule),
  '--- カート1 ---\n' +
    'ラベンダーの石けん 480円 × 3点 = 1440円\n' +
    'マグカップ 2350円 × 3点 = 7050円（注文5点のうち在庫3点まで）\n' +
    'リネンのふきん: 在庫切れのため注文できません\n' +
    '小計: 8490円\n' +
    '割引額: 849円\n' +
    '割引後小計: 7641円\n' +
    '消費税: 764円\n' +
    '税込商品合計: 8405円\n' +
    '送料: 0円\n' +
    'お支払い金額: 8405円'
);
checkString(
  '問題7: カート2の出力',
  buildCartReport('カート2', q7Cart2, goldRule),
  '--- カート2 ---\n' +
    'ラベンダーの石けん 480円 × 2点 = 960円\n' +
    '小計: 960円\n' +
    '割引額: 96円\n' +
    '割引後小計: 864円\n' +
    '消費税: 86円\n' +
    '税込商品合計: 950円\n' +
    '送料: 500円\n' +
    'お支払い金額: 1450円'
);

// 解答章の検算表（カート1の手順ごとの値）
checkNumber('問題7: 手順1 小計', 480 * 3 + 2350 * 3, 8490);
checkNumber('問題7: 手順2 割引額', Math.floor((8490 * 10) / 100), 849);
checkNumber('問題7: 手順3 割引後小計', 8490 - 849, 7641);
checkNumber('問題7: 手順4 消費税', Math.floor(7641 * TAX_RATE), 764);
checkNumber('問題7: 手順5 税込商品合計', 7641 + 764, 8405);
checkNumber('問題7: 手順6 送料', calcShippingFee(8405), 0);
checkNumber('問題7: カート2の消費税', Math.floor(864 * TAX_RATE), 86);
checkNumber('問題7: カート2の送料', calcShippingFee(950), 500);

// 別解（明細を先に組み立てて渡す形）でも同じ支払総額になること
function buildPaymentSummaryFromLines(
  lines: { label: string; lineTotal: number }[],
  rule: (subtotal: number) => number
): { subtotal: number; payableAmount: number } {
  let subtotal = 0;
  for (const { lineTotal } of lines) {
    subtotal = subtotal + lineTotal;
  }

  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;

  return { subtotal, payableAmount: totalWithTax + calcShippingFee(totalWithTax) };
}

const q7Alt = buildPaymentSummaryFromLines(buildCartLines(q7Cart1), goldRule);
checkNumber('問題7 別解: 小計が一致する', q7Alt.subtotal, 8490);
checkNumber('問題7 別解: 支払総額が一致する', q7Alt.payableAmount, 8405);

// 割引額に上限がかかること（クーポンが小計を超える場合）
const coupon10000 = (): number => 10000;
const q7Coupon = buildPaymentSummary(q7Cart2, coupon10000);
checkNumber('問題7: 割引額は小計を超えない', q7Coupon.discountAmount, 960);
checkNumber('問題7: 支払総額がマイナスにならない', q7Coupon.payableAmount, 500);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session08: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session08: ok');
