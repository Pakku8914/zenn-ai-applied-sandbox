/**
 * セッション13「ジェネリクス」の検証スクリプト。
 *
 * 本文（043）と練習問題の解答（045）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * console.log を1行ずつ出す章のコードは、この検証では
 * 「出力行を \n でつないだ文字列」を返す関数として表現している。
 *
 * 実行: docker compose exec ts npx tsx src/session13/verify.ts
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
// この章で共通に使うデータ（本文「この章で使う共通データ」と同じ）
// requirements.md の商品・カテゴリマスタから、この章で使わない
// description / imageUrl を省いたもの。値は変えていない。
// ---------------------------------------------------------------------------
type Product = { id: number; name: string; price: number; stock: number; categoryId: number };
type Category = { id: number; name: string; slug: string };
type CartItem = { id: number; userId: number; productId: number; quantity: number };

const products: readonly Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

const categories: readonly Category[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const cartItems: readonly CartItem[] = [
  { id: 1, userId: 1, productId: 1, quantity: 2 },
  { id: 2, userId: 1, productId: 3, quantity: 1 },
];

const tags: readonly string[] = ['ギフト', '新入荷', 'ロングセラー'];

/** 本文8節・問題4で使う1件（商品マスタの id=3 と同じ値） */
const mug: Product = { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 };
/** 問題4で使う1件（カテゴリマスタの id=2 と同じ値） */
const kitchen: Category = { id: 2, name: 'キッチン雑貨', slug: 'kitchen' };

// ---------------------------------------------------------------------------
// 章をまたいで使う関数（requirements.md の「確定した関数シグネチャ」）
// calcSubtotal はこの章でジェネリクスに一般化した形
// ---------------------------------------------------------------------------

/** 明細の小計（税抜・整数円） */
function calcSubtotal<T extends { price: number; quantity: number }>(lines: readonly T[]): number {
  return lines.reduce((total, line) => total + line.price * line.quantity, 0);
}

/** 送料。判定基準は税込商品合計 */
function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** 支払総額（計算手順の2〜7） */
function calcPayableAmount(subtotal: number, rule: (subtotal: number) => number): number {
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  return totalWithTax + calcShippingFee(totalWithTax); // 手順6・7
}

const noDiscount = (): number => 0;

// ---------------------------------------------------------------------------
// この章で作るジェネリックな部品（本文・解答で共有しているもの）
// ---------------------------------------------------------------------------

function firstItem<T>(items: readonly T[]): T | undefined {
  return items[0];
}

function lastItem<T>(items: readonly T[]): T | undefined {
  return items.at(-1);
}

function takeFirst<T>(items: readonly T[], count: number): T[] {
  return items.slice(0, count);
}

function findById<T extends { id: number }>(items: readonly T[], id: number): T | undefined {
  return items.find((item) => item.id === id);
}

function hasId<T extends { id: number }>(items: readonly T[], id: number): boolean {
  return items.some((item) => item.id === id);
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

function transformValues<K, V, W>(source: Map<K, V>, transform: (value: V) => W): Map<K, W> {
  const result = new Map<K, W>();
  for (const [key, value] of source) {
    result.set(key, transform(value));
  }
  return result;
}

function sumStockValue<T extends { price: number; stock: number }>(items: readonly T[]): number {
  return items.reduce((total, item) => total + item.price * item.stock, 0);
}

function pick<T, K extends keyof T>(item: T, key: K): T[K] {
  return item[key];
}

function pluck<T, K extends keyof T>(items: readonly T[], key: K): T[K][] {
  return items.map((item) => item[key]);
}

function formatRow<T, K extends keyof T>(item: T, keys: readonly K[]): string {
  return keys.map((key) => String(item[key])).join(' | ');
}

type Box<T> = { label: string; content: T };
type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };
type ValidationError = { field: string; message: string };
type ApiResult<T, E = string> = Result<T, E>;
type OrderRequest = { productId: number; quantity: number };
type ProductKey = keyof Product;

/** 商品を1件取得する（本文7節では requireProduct、問題6では findProduct という名前） */
function requireProduct(id: number): Result<Product, string> {
  const product = findById(products, id);
  if (product === undefined) {
    return { kind: 'error', error: `商品が見つかりません: id=${id}` };
  }
  return { kind: 'ok', value: product };
}

function describeQuantityResult(result: Result<number, string>): string {
  switch (result.kind) {
    case 'ok':
      return `数量: ${result.value}点`;
    case 'error':
      return `エラー: ${result.error}`;
  }
}

// ---------------------------------------------------------------------------
// 本文 1節：同じ関数を型ごとに書く痛み
// ---------------------------------------------------------------------------
function firstProduct(items: readonly Product[]): Product | undefined {
  return items[0];
}

function firstCategory(items: readonly Category[]): Category | undefined {
  return items[0];
}

function firstString(items: readonly string[]): string | undefined {
  return items[0];
}

function bodyDuplicated(): string {
  const product = firstProduct(products);
  const category = firstCategory(categories);
  const tag = firstString(tags);

  return [
    `最初の商品: ${product === undefined ? '(なし)' : product.name}`,
    `最初のカテゴリ: ${category === undefined ? '(なし)' : category.name}`,
    `最初のタグ: ${tag ?? '(なし)'}`,
  ].join('\n');
}

const bodyFirstExpected =
  '最初の商品: ラベンダーの石けん\n最初のカテゴリ: バス・ボディケア\n最初のタグ: ギフト';

checkString('本文1節: 型ごとに書いた3つの関数', bodyDuplicated(), bodyFirstExpected);

// ---------------------------------------------------------------------------
// 本文 2節：any で逃げると型が消える（Bad）／ジェネリクス（Good）
// any は Bad の実演としてのみ登場させる
// ---------------------------------------------------------------------------
function firstItemAny(items: readonly any[]): any {
  return items[0];
}

function bodyBadAny(): string {
  const first = firstItemAny(products);
  return `最初の商品（any）: ${first.name}\nタイポしても気づけない: ${first.nmae}`;
}

checkString(
  '本文2節 Bad: any だとタイポに気づけない',
  bodyBadAny(),
  '最初の商品（any）: ラベンダーの石けん\nタイポしても気づけない: undefined'
);

function bodyGoodGeneric(): string {
  const product = firstItem(products);
  const category = firstItem(categories);
  const tag = firstItem(tags);

  return [
    `最初の商品: ${product === undefined ? '(なし)' : product.name}`,
    `最初のカテゴリ: ${category === undefined ? '(なし)' : category.name}`,
    `最初のタグ: ${tag ?? '(なし)'}`,
  ].join('\n');
}

checkString('本文2節 Good: ジェネリック関数1つ', bodyGoodGeneric(), bodyFirstExpected);

// ---------------------------------------------------------------------------
// 本文 3節：型引数は呼ぶときに決まる
// ---------------------------------------------------------------------------
function bodyInferenceProof(): string {
  const product = firstItem<Product>(products);
  return product === undefined ? '(なし)' : `${product.name}：${product.price}円`;
}

checkString('本文3節: 型引数を明示しても結果は同じ', bodyInferenceProof(), 'ラベンダーの石けん：480円');

// ---------------------------------------------------------------------------
// 本文 4節：Array<T> / Map<K, V> / Set<T> の種明かし
// ---------------------------------------------------------------------------
function bodyArrayGenerics(): string {
  const prices: Array<number> = [480, 1800, 2350];
  const productNameById: Map<number, string> = new Map();
  const tagSet: Set<string> = new Set(tags);

  for (const product of products) {
    productNameById.set(product.id, product.name);
  }

  const names = products.map((product) => product.name);
  const stocks = products.map((product) => product.stock);

  return [
    `価格の件数: ${prices.length}`,
    `id=3 → ${productNameById.get(3) ?? '(なし)'}`,
    `タグの種類: ${tagSet.size}`,
    `商品名: ${names.join(' / ')}`,
    `在庫の合計: ${stocks.reduce((total, stock) => total + stock, 0)}`,
  ].join('\n');
}

checkString(
  '本文4節: 標準ライブラリのジェネリクス',
  bodyArrayGenerics(),
  '価格の件数: 3\n' +
    'id=3 → マグカップ\n' +
    'タグの種類: 3\n' +
    '商品名: ラベンダーの石けん / ハンドクリーム / マグカップ / リネンのふきん / コットンのトートバッグ\n' +
    '在庫の合計: 44'
);

// ---------------------------------------------------------------------------
// 本文 5節：制約（extends）
// ---------------------------------------------------------------------------
function bodyFindById(): string {
  const product = findById(products, 3);
  const category = findById(categories, 2);
  const cartItem = findById(cartItems, 2);
  const missing = findById(products, 99);

  return [
    `商品: ${product === undefined ? '該当なし' : `${product.name}（${product.price}円）`}`,
    `カテゴリ: ${category === undefined ? '該当なし' : `${category.name}（${category.slug}）`}`,
    `カート明細: ${
      cartItem === undefined
        ? '該当なし'
        : `productId=${cartItem.productId} × ${cartItem.quantity}点`
    }`,
    `見つからない: ${missing === undefined ? '該当なし' : missing.name}`,
  ].join('\n');
}

checkString(
  '本文5節: 制約付きジェネリクスで3種類のデータを検索',
  bodyFindById(),
  '商品: マグカップ（2350円）\n' +
    'カテゴリ: キッチン雑貨（kitchen）\n' +
    'カート明細: productId=3 × 1点\n' +
    '見つからない: 該当なし'
);

// Bad：共通部分の型だけで受けると id 以外が読めなくなる
function findByIdLoose(
  items: readonly { id: number }[],
  id: number
): { id: number } | undefined {
  return items.find((item) => item.id === id);
}

function bodyBadLooseFind(): string {
  const found = findByIdLoose(products, 3);
  return found === undefined ? '該当なし' : `id だけは読める: ${found.id}`;
}

checkString('本文5節 Bad: 戻り値が { id: number } に潰れる', bodyBadLooseFind(), 'id だけは読める: 3');

function bodyGoodGenericFind(): string {
  const found = findById(products, 3);
  if (found === undefined) {
    return '該当なし';
  }
  return `${found.name}：${found.price}円 / 在庫${found.stock}点`;
}

checkString(
  '本文5節 Good: T が Product のまま運ばれる',
  bodyGoodGenericFind(),
  'マグカップ：2350円 / 在庫3点'
);

// ---------------------------------------------------------------------------
// 本文 6節：複数の型引数
// ---------------------------------------------------------------------------
function bodyBuildIndex(): string {
  const productById = buildIndex(products, (product) => product.id);
  const categoryBySlug = buildIndex(categories, (category) => category.slug);

  const target = productById.get(3);
  const target2 = categoryBySlug.get('kitchen');

  return [
    `商品の索引: ${productById.size}件 / id=3 → ${target === undefined ? '(なし)' : target.name}`,
    `カテゴリの索引: ${categoryBySlug.size}件 / slug=kitchen → ${
      target2 === undefined ? '(なし)' : target2.name
    }`,
  ].join('\n');
}

checkString(
  '本文6節: buildIndex で Map を作る',
  bodyBuildIndex(),
  '商品の索引: 5件 / id=3 → マグカップ\nカテゴリの索引: 3件 / slug=kitchen → キッチン雑貨'
);

// ---------------------------------------------------------------------------
// 本文 7節：ジェネリックな型エイリアス（Box<T> / Result<T, E>）
// ---------------------------------------------------------------------------
/** 本文7節の describeBox（区切りは " = "） */
function describeBoxBody<T>(box: Box<T>, format: (content: T) => string): string {
  return `${box.label} = ${format(box.content)}`;
}

function bodyBox(): string {
  const priceBox: Box<number> = { label: '価格', content: 480 };
  const tagBox: Box<string> = { label: 'タグ', content: 'ギフト' };
  const cartBox: Box<CartItem> = {
    label: 'カート明細',
    content: { id: 1, userId: 1, productId: 1, quantity: 2 },
  };

  return [
    describeBoxBody(priceBox, (price) => `${price}円`),
    describeBoxBody(tagBox, (tag) => tag),
    describeBoxBody(cartBox, (item) => `productId=${item.productId} × ${item.quantity}点`),
  ].join('\n');
}

checkString(
  '本文7節: Box<T> を3種類の中身で使う',
  bodyBox(),
  '価格 = 480円\nタグ = ギフト\nカート明細 = productId=1 × 2点'
);

/** 本文7節の toQuantity（空文字チェックなし。問題3ではそれを足す） */
function bodyToQuantity(input: string): Result<number, string> {
  const value = Number(input);

  if (Number.isNaN(value)) {
    return { kind: 'error', error: `数量が数値ではありません: ${input}` };
  }
  if (!Number.isInteger(value)) {
    return { kind: 'error', error: '数量は整数で指定してください' };
  }
  if (value <= 0) {
    return { kind: 'error', error: '数量は1以上で指定してください' };
  }
  return { kind: 'ok', value };
}

function bodyResult(): string {
  const productResult = requireProduct(3);
  const missingResult = requireProduct(99);

  return [
    describeQuantityResult(bodyToQuantity('2')),
    describeQuantityResult(bodyToQuantity('abc')),
    describeQuantityResult(bodyToQuantity('1.5')),
    describeQuantityResult(bodyToQuantity('0')),
    productResult.kind === 'ok' ? `商品: ${productResult.value.name}` : productResult.error,
    missingResult.kind === 'ok' ? `商品: ${missingResult.value.name}` : missingResult.error,
  ].join('\n');
}

checkString(
  '本文7節: Result<T, E> の素形',
  bodyResult(),
  '数量: 2点\n' +
    'エラー: 数量が数値ではありません: abc\n' +
    'エラー: 数量は整数で指定してください\n' +
    'エラー: 数量は1以上で指定してください\n' +
    '商品: マグカップ\n' +
    '商品が見つかりません: id=99'
);

// ---------------------------------------------------------------------------
// 本文 8節：keyof と pick
// ---------------------------------------------------------------------------
function bodyPick(): string {
  const bodyProductKey: ProductKey = 'price';

  return [
    `name: ${pick(mug, 'name')}`,
    `price: ${pick(mug, 'price')}`,
    `categoryId: ${pick(mug, 'categoryId')}`,
    `key1: ${bodyProductKey}`,
    `商品名の一覧: ${pluck(products, 'name').join(' / ')}`,
    `価格の一覧: ${pluck(products, 'price').join(' / ')}`,
  ].join('\n');
}

checkString(
  '本文8節: keyof と pick / pluck',
  bodyPick(),
  'name: マグカップ\n' +
    'price: 2350\n' +
    'categoryId: 2\n' +
    'key1: price\n' +
    '商品名の一覧: ラベンダーの石けん / ハンドクリーム / マグカップ / リネンのふきん / コットンのトートバッグ\n' +
    '価格の一覧: 480 / 1800 / 2350 / 990 / 2800'
);

// ---------------------------------------------------------------------------
// 本文 9節：デフォルト型引数
// ---------------------------------------------------------------------------
function createEmptyList<T = string>(): T[] {
  return [];
}

function bodyDefaultTypeArg(): string {
  const okResult: ApiResult<Product> = { kind: 'ok', value: mug };
  const errorResult: ApiResult<Product> = {
    kind: 'error',
    error: '商品が見つかりません: id=99',
  };
  const detailedError: ApiResult<number, ValidationError> = {
    kind: 'error',
    error: { field: 'quantity', message: '数量は1以上で指定してください' },
  };

  const tagList = createEmptyList();
  const priceList = createEmptyList<number>();

  return [
    `成功: ${okResult.kind === 'ok' ? okResult.value.name : ''}`,
    `失敗（文字列のエラー）: ${errorResult.kind === 'error' ? errorResult.error : ''}`,
    `失敗（詳細なエラー）: ${
      detailedError.kind === 'error'
        ? `${detailedError.error.field} - ${detailedError.error.message}`
        : ''
    }`,
    `空のリスト: ${tagList.length}件 / ${priceList.length}件`,
  ].join('\n');
}

checkString(
  '本文9節: デフォルト型引数',
  bodyDefaultTypeArg(),
  '成功: マグカップ\n' +
    '失敗（文字列のエラー）: 商品が見つかりません: id=99\n' +
    '失敗（詳細なエラー）: quantity - 数量は1以上で指定してください\n' +
    '空のリスト: 0件 / 0件'
);

// ---------------------------------------------------------------------------
// 本文 10節：使いすぎない判断（Bad / Good）と calcSubtotal の一般化
// ---------------------------------------------------------------------------
function describeName(item: { name: string }): string {
  return `商品名: ${item.name}`;
}

const bodyCartLines = [
  { name: 'ラベンダーの石けん', price: 480, quantity: 2 },
  { name: 'ハンドクリーム', price: 1800, quantity: 1 },
  { name: 'コットンのトートバッグ', price: 2800, quantity: 1 },
];

const bodyOrderLines = [
  { productId: 3, price: 2350, quantity: 2 },
  { productId: 1, price: 480, quantity: 1 },
];

function bodyGenericSubtotal(): string {
  return [
    describeName(mug),
    `カートの小計: ${calcSubtotal(bodyCartLines)}円`,
    `カートの支払総額: ${calcPayableAmount(calcSubtotal(bodyCartLines), noDiscount)}円`,
    `注文明細の小計: ${calcSubtotal(bodyOrderLines)}円`,
  ].join('\n');
}

checkString(
  '本文10節: 制約付きに一般化した calcSubtotal',
  bodyGenericSubtotal(),
  '商品名: マグカップ\nカートの小計: 5560円\nカートの支払総額: 6116円\n注文明細の小計: 5180円'
);

// 支払総額の内訳（本文の説明に書いた数値）
checkNumber('本文10節: カートの小計', calcSubtotal(bodyCartLines), 5560);
checkNumber('本文10節: 消費税', Math.floor(5560 * TAX_RATE), 556);
checkNumber('本文10節: 税込商品合計', 5560 + 556, 6116);
checkNumber('本文10節: 送料', calcShippingFee(6116), 0);

// ---------------------------------------------------------------------------
// 問題1：重複した3つの関数を1つにまとめる
// ---------------------------------------------------------------------------
function solveQ1(): string {
  const firstProductValue = firstItem(products);
  const lastProductValue = lastItem(products);
  const emptyProducts: readonly Product[] = [];
  const firstOfEmpty = firstItem(emptyProducts);
  const firstTwoNames = takeFirst(products, 2).map((product) => product.name);

  return [
    `最初の商品: ${firstProductValue === undefined ? '(なし)' : firstProductValue.name}`,
    `最後の商品: ${lastProductValue === undefined ? '(なし)' : lastProductValue.name}`,
    `最初のタグ: ${firstItem(tags) ?? '(なし)'}`,
    `最後のタグ: ${lastItem(tags) ?? '(なし)'}`,
    `先頭2件: ${firstTwoNames.join(' / ')}`,
    `空配列の先頭: ${firstOfEmpty === undefined ? '(なし)' : firstOfEmpty.name}`,
  ].join('\n');
}

checkString(
  '問題1: 出力6行',
  solveQ1(),
  '最初の商品: ラベンダーの石けん\n' +
    '最後の商品: コットンのトートバッグ\n' +
    '最初のタグ: ギフト\n' +
    '最後のタグ: ロングセラー\n' +
    '先頭2件: ラベンダーの石けん / ハンドクリーム\n' +
    '空配列の先頭: (なし)'
);

// 問題1 別解：at(-1) の代わりにインデックスで末尾を読む（結果は同じ）
function lastItemByIndex<T>(items: readonly T[]): T | undefined {
  return items[items.length - 1];
}

const q1AlternativeLast = lastItemByIndex(products);
checkString(
  '問題1 別解: length - 1 でも同じ',
  q1AlternativeLast === undefined ? '(なし)' : q1AlternativeLast.name,
  'コットンのトートバッグ'
);
const q1EmptyForAlternative: readonly Product[] = [];
checkBoolean(
  '問題1 別解: 空配列でも undefined',
  lastItemByIndex(q1EmptyForAlternative) === undefined,
  true
);

// takeFirst は元の配列を変えない
checkNumber('問題1: takeFirst は非破壊', products.length, 5);

// ---------------------------------------------------------------------------
// 問題2：制約付きジェネリクスで「id で探す」を共通化する
// ---------------------------------------------------------------------------
function describeProduct(id: number): string {
  const product = findById(products, id);

  if (product === undefined) {
    return '該当する商品がありません';
  }
  return `${product.name}（${product.price}円）`;
}

function solveQ2(): string {
  const category = findById(categories, 2);
  const cartItem = findById(cartItems, 2);

  return [
    `商品 id=3: ${describeProduct(3)}`,
    `商品 id=99: ${describeProduct(99)}`,
    `カテゴリ id=2: ${
      category === undefined ? '該当なし' : `${category.name}（${category.slug}）`
    }`,
    `カート明細 id=2: ${
      cartItem === undefined
        ? '該当なし'
        : `productId=${cartItem.productId} × ${cartItem.quantity}点`
    }`,
    `id=4 は存在する: ${hasId(products, 4)}`,
    `id=99 は存在する: ${hasId(products, 99)}`,
  ].join('\n');
}

checkString(
  '問題2: 出力6行',
  solveQ2(),
  '商品 id=3: マグカップ（2350円）\n' +
    '商品 id=99: 該当する商品がありません\n' +
    'カテゴリ id=2: キッチン雑貨（kitchen）\n' +
    'カート明細 id=2: productId=3 × 1点\n' +
    'id=4 は存在する: true\n' +
    'id=99 は存在する: false'
);

// 問題2 別解：hasId を findById で実装する（結果は同じ）
function hasIdByFind<T extends { id: number }>(items: readonly T[], id: number): boolean {
  return findById(items, id) !== undefined;
}

checkBoolean('問題2 別解: hasId を findById で実装（id=4）', hasIdByFind(products, 4), true);
checkBoolean('問題2 別解: hasId を findById で実装（id=99）', hasIdByFind(products, 99), false);

// ---------------------------------------------------------------------------
// 問題3：ジェネリックな型エイリアスを定義する
// ---------------------------------------------------------------------------
/** 問題3の describeBox（区切りは ": "） */
function describeBox<T>(box: Box<T>, format: (content: T) => string): string {
  return `${box.label}: ${format(box.content)}`;
}

function toQuantity(input: string): Result<number, string> {
  if (input.trim() === '') {
    return { kind: 'error', error: '数量が入力されていません' };
  }

  const value = Number(input);

  if (Number.isNaN(value)) {
    return { kind: 'error', error: `数量が数値ではありません: ${input}` };
  }
  if (!Number.isInteger(value)) {
    return { kind: 'error', error: '数量は整数で指定してください' };
  }
  if (value <= 0) {
    return { kind: 'error', error: '数量は1以上で指定してください' };
  }

  return { kind: 'ok', value };
}

function solveQ3(): string {
  const priceBox: Box<number> = { label: '価格', content: 480 };
  const tagBox: Box<string> = { label: 'タグ', content: 'ギフト' };
  const cartBox: Box<CartItem> = {
    label: 'カート明細',
    content: { id: 1, userId: 1, productId: 1, quantity: 2 },
  };

  const lines: string[] = [
    describeBox(priceBox, (price) => `${price}円`),
    describeBox(tagBox, (tag) => tag),
    describeBox(cartBox, (item) => `productId=${item.productId} × ${item.quantity}点`),
  ];

  for (const input of ['2', '', 'abc', '2.5', '0']) {
    lines.push(`'${input}' → ${describeQuantityResult(toQuantity(input))}`);
  }

  return lines.join('\n');
}

checkString(
  '問題3: 出力8行',
  solveQ3(),
  '価格: 480円\n' +
    'タグ: ギフト\n' +
    'カート明細: productId=1 × 2点\n' +
    "'2' → 数量: 2点\n" +
    "'' → エラー: 数量が入力されていません\n" +
    "'abc' → エラー: 数量が数値ではありません: abc\n" +
    "'2.5' → エラー: 数量は整数で指定してください\n" +
    "'0' → エラー: 数量は1以上で指定してください"
);

// 解説③の裏付け：Number('') は NaN ではなく 0
checkNumber("問題3: Number('') は 0", Number(''), 0);
checkBoolean("問題3: Number('') は NaN ではない", Number.isNaN(Number('')), false);

// ---------------------------------------------------------------------------
// 問題4：keyof でプロパティ名を型安全に受け取る
// ---------------------------------------------------------------------------
function solveQ4(): string {
  const totalStock = pluck(products, 'stock').reduce((total, stock) => total + stock, 0);

  return [
    `name: ${pick(mug, 'name')}`,
    `price: ${pick(mug, 'price')}`,
    `categoryId: ${pick(mug, 'categoryId')}`,
    `商品名の一覧: ${pluck(products, 'name').join(' / ')}`,
    `価格の一覧: ${pluck(products, 'price').join(' / ')}`,
    `在庫の合計: ${totalStock}点`,
    `商品の行: ${formatRow(mug, ['id', 'name', 'price'])}`,
    `カテゴリの行: ${formatRow(kitchen, ['id', 'name', 'slug'])}`,
  ].join('\n');
}

checkString(
  '問題4: 出力8行',
  solveQ4(),
  'name: マグカップ\n' +
    'price: 2350\n' +
    'categoryId: 2\n' +
    '商品名の一覧: ラベンダーの石けん / ハンドクリーム / マグカップ / リネンのふきん / コットンのトートバッグ\n' +
    '価格の一覧: 480 / 1800 / 2350 / 990 / 2800\n' +
    '在庫の合計: 44点\n' +
    '商品の行: 3 | マグカップ | 2350\n' +
    'カテゴリの行: 2 | キッチン雑貨 | kitchen'
);

// 問題4 別解：pluck を pick で組み立てる（結果は同じ）
function pluckByPick<T, K extends keyof T>(items: readonly T[], key: K): T[K][] {
  return items.map((item) => pick(item, key));
}

checkString(
  '問題4 別解: pluck を pick で組み立てる',
  pluckByPick(products, 'name').join(' / '),
  pluck(products, 'name').join(' / ')
);

// ---------------------------------------------------------------------------
// 問題5：複数の型引数で配列を Map に変換する
// ---------------------------------------------------------------------------
function solveQ5(): string {
  const productById = buildIndex(products, (product) => product.id);
  const categoryBySlug = buildIndex(categories, (category) => category.slug);

  const target = productById.get(3);
  const fabric = categoryBySlug.get('fabric');

  const lines: string[] = [
    `商品の索引: ${productById.size}件 / id=3 → ${target === undefined ? '(なし)' : target.name}`,
    `カテゴリの索引: ${categoryBySlug.size}件 / slug=fabric → ${
      fabric === undefined ? '(なし)' : fabric.name
    }`,
  ];

  const productsByCategoryId = groupBy(products, (product) => product.categoryId);

  for (const category of categories) {
    const items = productsByCategoryId.get(category.id) ?? [];
    lines.push(`${category.name}: ${items.map((item) => item.name).join(' / ')}`);
  }

  const stockValueByCategoryId = transformValues(productsByCategoryId, (items) =>
    sumStockValue(items)
  );

  for (const category of categories) {
    lines.push(`在庫金額 ${category.name}: ${stockValueByCategoryId.get(category.id) ?? 0}円`);
  }

  return lines.join('\n');
}

checkString(
  '問題5: 出力8行',
  solveQ5(),
  '商品の索引: 5件 / id=3 → マグカップ\n' +
    'カテゴリの索引: 3件 / slug=fabric → ファブリック\n' +
    'バス・ボディケア: ラベンダーの石けん / ハンドクリーム\n' +
    'キッチン雑貨: マグカップ\n' +
    'ファブリック: リネンのふきん / コットンのトートバッグ\n' +
    '在庫金額 バス・ボディケア: 33120円\n' +
    '在庫金額 キッチン雑貨: 7050円\n' +
    '在庫金額 ファブリック: 14000円'
);

// 在庫金額の内訳（解答の表に書いた数値）
checkNumber('問題5: 石けんの在庫金額', 480 * 24, 11520);
checkNumber('問題5: ハンドクリームの在庫金額', 1800 * 12, 21600);
checkNumber('問題5: バス・ボディケアの合計', 11520 + 21600, 33120);
checkNumber('問題5: マグカップの在庫金額', 2350 * 3, 7050);
checkNumber('問題5: ふきんの在庫金額', 990 * 0, 0);
checkNumber('問題5: トートバッグの在庫金額', 2800 * 5, 14000);
checkNumber('問題5: 全体の在庫金額', sumStockValue(products), 54170);

// 問題5 別解：groupBy を reduce で書く（結果は同じ）
function groupByReduce<T, K>(items: readonly T[], getKey: (item: T) => K): Map<K, T[]> {
  return items.reduce((groups, item) => {
    const key = getKey(item);
    const current = groups.get(key) ?? [];
    groups.set(key, [...current, item]);
    return groups;
  }, new Map<K, T[]>());
}

const q5ByReduce = groupByReduce(products, (product) => product.categoryId);
checkString(
  '問題5 別解: reduce 版の groupBy',
  (q5ByReduce.get(3) ?? []).map((product) => product.name).join(' / '),
  'リネンのふきん / コットンのトートバッグ'
);

// buildIndex はキーが重複すると後から来たものが上書きする（設計と運用のポイント）
const q5DuplicatedIndex = buildIndex(products, (product) => product.categoryId);
checkNumber('問題5: キーが重複する buildIndex の件数', q5DuplicatedIndex.size, 3);
const q5OverwrittenCategory1 = q5DuplicatedIndex.get(1);
checkString(
  '問題5: 重複キーは後勝ちになる',
  q5OverwrittenCategory1 === undefined ? '(なし)' : q5OverwrittenCategory1.name,
  'ハンドクリーム'
);

// ---------------------------------------------------------------------------
// 問題6：デフォルト型引数と Result で注文チェックを組み立てる
// ---------------------------------------------------------------------------
function mapResult<T, U, E>(result: Result<T, E>, transform: (value: T) => U): Result<U, E> {
  if (result.kind === 'error') {
    return result;
  }
  return { kind: 'ok', value: transform(result.value) };
}

function validateQuantity(quantity: number): ApiResult<number, ValidationError> {
  if (!Number.isInteger(quantity)) {
    return { kind: 'error', error: { field: 'quantity', message: '数量は整数で指定してください' } };
  }
  if (quantity <= 0) {
    return { kind: 'error', error: { field: 'quantity', message: '数量は1以上で指定してください' } };
  }
  return { kind: 'ok', value: quantity };
}

function checkStock(product: Product, quantity: number): ApiResult<Product> {
  if (product.stock <= 0) {
    return { kind: 'error', error: `在庫がありません（${product.name}）` };
  }
  if (product.stock < quantity) {
    return { kind: 'error', error: `在庫が足りません（${product.name}: 在庫${product.stock}点）` };
  }
  return { kind: 'ok', value: product };
}

function formatValidationError(error: ValidationError): string {
  return `${error.field}: ${error.message}`;
}

function checkout(request: OrderRequest): ApiResult<number> {
  const quantityResult = validateQuantity(request.quantity);
  if (quantityResult.kind === 'error') {
    return { kind: 'error', error: formatValidationError(quantityResult.error) };
  }

  const productResult = requireProduct(request.productId);
  if (productResult.kind === 'error') {
    return productResult;
  }

  const stockResult = checkStock(productResult.value, quantityResult.value);
  if (stockResult.kind === 'error') {
    return stockResult;
  }

  const subtotal = calcSubtotal([
    { price: stockResult.value.price, quantity: quantityResult.value },
  ]);
  return { kind: 'ok', value: calcPayableAmount(subtotal, noDiscount) };
}

const q6Requests: readonly OrderRequest[] = [
  { productId: 3, quantity: 2 },
  { productId: 4, quantity: 1 },
  { productId: 3, quantity: 5 },
  { productId: 99, quantity: 1 },
  { productId: 1, quantity: 0 },
];

function solveQ6(): string {
  const lines: string[] = [];

  for (const request of q6Requests) {
    const label = `id=${request.productId} × ${request.quantity}点`;
    const result = checkout(request);

    if (result.kind === 'error') {
      lines.push(`${label} → エラー: ${result.error}`);
    } else {
      lines.push(`${label} → お支払い${result.value}円`);
    }
  }

  const nameResult = mapResult(requireProduct(3), (product) => product.name);
  lines.push(
    `商品名だけ取り出す: ${nameResult.kind === 'ok' ? nameResult.value : nameResult.error}`
  );

  return lines.join('\n');
}

checkString(
  '問題6: 出力6行',
  solveQ6(),
  'id=3 × 2点 → お支払い5170円\n' +
    'id=4 × 1点 → エラー: 在庫がありません（リネンのふきん）\n' +
    'id=3 × 5点 → エラー: 在庫が足りません（マグカップ: 在庫3点）\n' +
    'id=99 × 1点 → エラー: 商品が見つかりません: id=99\n' +
    'id=1 × 0点 → エラー: quantity: 数量は1以上で指定してください\n' +
    '商品名だけ取り出す: マグカップ'
);

// 支払総額の内訳（解答の表に書いた数値）
checkNumber('問題6 手順1 小計', calcSubtotal([{ price: 2350, quantity: 2 }]), 4700);
checkNumber('問題6 手順4 消費税', Math.floor(4700 * TAX_RATE), 470);
checkNumber('問題6 手順5 税込商品合計', 4700 + 470, 5170);
checkNumber('問題6 手順6 送料', calcShippingFee(5170), 0);
checkNumber('問題6 手順7 支払総額', calcPayableAmount(4700, noDiscount), 5170);

// 数量の検証は整数チェックが先（小数は「整数で指定してください」になる）
const q6FractionResult = validateQuantity(1.5);
checkString(
  '問題6: 小数の数量',
  q6FractionResult.kind === 'error' ? formatValidationError(q6FractionResult.error) : 'ok',
  'quantity: 数量は整数で指定してください'
);

// mapResult は失敗をそのまま通す
const q6MappedError = mapResult(requireProduct(99), (product) => product.name);
checkString(
  '問題6: mapResult は失敗を素通しする',
  q6MappedError.kind === 'error' ? q6MappedError.error : 'ok',
  '商品が見つかりません: id=99'
);

// 問題6 別解：成功パスを mapResult でつなぐ（在庫チェックは挟めない）
function checkoutWithMap(request: OrderRequest): ApiResult<number> {
  const quantityResult = validateQuantity(request.quantity);
  if (quantityResult.kind === 'error') {
    return { kind: 'error', error: formatValidationError(quantityResult.error) };
  }

  const quantity = quantityResult.value;

  return mapResult(requireProduct(request.productId), (product) =>
    calcPayableAmount(calcSubtotal([{ price: product.price, quantity }]), noDiscount)
  );
}

const q6AlternativeOk = checkoutWithMap({ productId: 3, quantity: 2 });
checkNumber('問題6 別解: 成功時は同じ金額', q6AlternativeOk.kind === 'ok' ? q6AlternativeOk.value : -1, 5170);

// 別解では在庫0でも成功してしまう（在庫チェックを挟めないことの裏付け）
const q6AlternativeSoldOut = checkoutWithMap({ productId: 4, quantity: 1 });
checkBoolean('問題6 別解: 在庫切れを検出できない', q6AlternativeSoldOut.kind === 'ok', true);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session13: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session13: ok');
