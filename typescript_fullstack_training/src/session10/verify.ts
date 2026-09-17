/**
 * セッション10「配列メソッドとMap・Set」の検証スクリプト。
 *
 * 本文（029）と練習問題の解答（031）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * console.log を1行ずつ出す章のコードは、この検証では
 * 「出力行を \n でつないだ文字列」を返す関数として表現している。
 *
 * 実行: docker compose exec ts npx tsx src/session10/verify.ts
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
// この章で共通に使うマスタデータ（本文「この章で使う共通データ」と同じ）
// requirements.md の商品・カテゴリマスタから、この章で使わない
// description / imageUrl を省いたもの。値は変えていない。
// ---------------------------------------------------------------------------
const categories = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const products = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

// ---------------------------------------------------------------------------
// 章をまたいで使う関数（requirements.md の「確定した関数シグネチャ」）
// ---------------------------------------------------------------------------

/** 明細の小計（税抜・整数円） */
const calcSubtotal = (lines: { price: number; quantity: number }[]): number =>
  lines.reduce((total, line) => total + line.price * line.quantity, 0);

/** 送料。判定基準は税込商品合計 */
const calcShippingFee = (totalWithTax: number): number =>
  totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;

/** 割引率から「割引額を返す関数」を作る高階関数（S06） */
const makePercentDiscount = (percent: number): ((subtotal: number) => number) => {
  return (subtotal: number): number => Math.floor((subtotal * percent) / 100);
};

/** 支払総額（計算手順の2〜7） */
const calcPayableAmount = (subtotal: number, rule: (subtotal: number) => number): number => {
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  return totalWithTax + calcShippingFee(totalWithTax); // 手順6・7
};

/** 商品リストの在庫金額合計（price × stock） */
const sumStockValue = (items: { price: number; stock: number }[]): number =>
  items.reduce((total, item) => total + item.price * item.stock, 0);

// ---------------------------------------------------------------------------
// 本文 1節：map（src/session10/map-basics.ts）
// ---------------------------------------------------------------------------
function bodyProductNames(): string {
  const productNames = products.map((product) => product.name);
  return `${productNames.join(' / ')}\n${productNames.length}件`;
}

checkString(
  '本文1節: 商品名の配列',
  bodyProductNames(),
  'ラベンダーの石けん / ハンドクリーム / マグカップ / リネンのふきん / コットンのトートバッグ\n5件'
);

function bodyPriceLabels(): string {
  const priceLabels = products.map((product) => `${product.name}：${product.price}円`);

  const lines: string[] = [];
  for (const label of priceLabels) {
    lines.push(label);
  }
  return lines.join('\n');
}

checkString(
  '本文1節: 表示用の文字列に変換',
  bodyPriceLabels(),
  'ラベンダーの石けん：480円\n' +
    'ハンドクリーム：1800円\n' +
    'マグカップ：2350円\n' +
    'リネンのふきん：990円\n' +
    'コットンのトートバッグ：2800円'
);

function bodyNumberedNames(): string {
  return products.map((product, index) => `${index + 1}. ${product.name}`).join('\n');
}

checkString(
  '本文1節: インデックスで連番を振る',
  bodyNumberedNames(),
  '1. ラベンダーの石けん\n' +
    '2. ハンドクリーム\n' +
    '3. マグカップ\n' +
    '4. リネンのふきん\n' +
    '5. コットンのトートバッグ'
);

function bodyMapIsNonDestructive(): string {
  const doubledStocks = products.map((product) => product.stock * 2);
  return `${doubledStocks.join(' / ')}\n${products.map((product) => product.stock).join(' / ')}`;
}

checkString(
  '本文1節: map は元の配列を変えない',
  bodyMapIsNonDestructive(),
  '48 / 24 / 6 / 0 / 10\n24 / 12 / 3 / 0 / 5'
);

// セッション6で自作した高階関数（src/session10/handmade.ts）
function bodyTransformAll(): string {
  const transformAll = (values: number[], transform: (value: number) => number): number[] => {
    const result: number[] = [];
    for (const value of values) {
      result.push(transform(value));
    }
    return result;
  };

  return transformAll([480, 1800, 2350], (price) => price * 2).join(' / ');
}

checkString('本文1節: 自作の高階関数', bodyTransformAll(), '960 / 3600 / 4700');

// Bad/Good（bad-loop.ts / good-map.ts）はどちらも 5 を出力する
function bodyBadLoopCount(): number {
  const labels: string[] = [];

  for (let i = 0; i < products.length; i++) {
    const product = products[i];
    if (product === undefined) {
      continue;
    }
    labels.push(`${product.name}：${product.price}円`);
  }
  return labels.length;
}

function bodyGoodMapCount(): number {
  return products.map((product) => `${product.name}：${product.price}円`).length;
}

checkNumber('本文1節 Bad: for ループ版の件数', bodyBadLoopCount(), 5);
checkNumber('本文1節 Good: map 版の件数', bodyGoodMapCount(), 5);

// ---------------------------------------------------------------------------
// 本文 2節：filter（src/session10/filter-basics.ts）
// ---------------------------------------------------------------------------
function bodyFilterBasics(): string {
  const inStockProducts = products.filter((product) => product.stock > 0);
  const soldOutProducts = products.filter((product) => product.stock === 0);

  const lines: string[] = [];
  lines.push(`${inStockProducts.length}件`);
  lines.push(inStockProducts.map((product) => product.name).join(' / '));
  lines.push(soldOutProducts.map((product) => product.name).join(' / '));
  return lines.join('\n');
}

checkString(
  '本文2節: filter で絞り込む',
  bodyFilterBasics(),
  '4件\nラベンダーの石けん / ハンドクリーム / マグカップ / コットンのトートバッグ\nリネンのふきん'
);

function bodyFilterEmpty(): string {
  const luxuryProducts = products.filter((product) => product.price >= 10000);
  return `${luxuryProducts.length}件 / 空配列か: ${luxuryProducts.length === 0}`;
}

checkString('本文2節: 該当0件は空配列', bodyFilterEmpty(), '0件 / 空配列か: true');

// 本文2節：手書きのループと「filter → map」は同じ結果になる
function bodyBadFilterNames(): string {
  const names: string[] = [];
  for (const product of products) {
    if (product.stock > 0) {
      names.push(product.name);
    }
  }
  return names.join(' / ');
}

function bodyGoodFilterNames(): string {
  return products
    .filter((product) => product.stock > 0)
    .map((product) => product.name)
    .join(' / ');
}

checkString(
  '本文2節: 手書きループの結果',
  bodyBadFilterNames(),
  'ラベンダーの石けん / ハンドクリーム / マグカップ / コットンのトートバッグ'
);
checkString('本文2節: filter → map の結果', bodyGoodFilterNames(), bodyBadFilterNames());

// ---------------------------------------------------------------------------
// 本文 3節：find / some / every（src/session10/find-basics.ts）
// ---------------------------------------------------------------------------
function bodyFindBasics(): string {
  const lines: string[] = [];

  const expensiveProduct = products.find((product) => product.price >= 2000);
  if (expensiveProduct === undefined) {
    lines.push('該当する商品はありません');
  } else {
    lines.push(`${expensiveProduct.name}：${expensiveProduct.price}円`);
  }

  const cheapProduct = products.find((product) => product.price < 300);
  if (cheapProduct === undefined) {
    lines.push('該当する商品はありません');
  } else {
    lines.push(`${cheapProduct.name}：${cheapProduct.price}円`);
  }

  return lines.join('\n');
}

checkString('本文3節: find', bodyFindBasics(), 'マグカップ：2350円\n該当する商品はありません');

checkNumber(
  '本文3節: findIndex',
  products.findIndex((product) => product.stock === 0),
  3
);

function bodySomeEvery(): string {
  const lines: string[] = [];
  lines.push(`在庫切れの商品がある: ${products.some((product) => product.stock === 0)}`);
  lines.push(`すべて在庫がある: ${products.every((product) => product.stock > 0)}`);
  lines.push(`すべて480円以上: ${products.every((product) => product.price >= 480)}`);
  lines.push(`1万円以上の商品がある: ${products.some((product) => product.price >= 10000)}`);
  return lines.join('\n');
}

checkString(
  '本文3節: some / every',
  bodySomeEvery(),
  '在庫切れの商品がある: true\n' +
    'すべて在庫がある: false\n' +
    'すべて480円以上: true\n' +
    '1万円以上の商品がある: false'
);

function bodyEmptySomeEvery(): string {
  const emptyCart: { name: string; quantity: number }[] = [];
  return (
    `some: ${emptyCart.some((line) => line.quantity > 0)}\n` +
    `every: ${emptyCart.every((line) => line.quantity > 0)}`
  );
}

checkString('本文3節: 空配列の some / every', bodyEmptySomeEvery(), 'some: false\nevery: true');

// ---------------------------------------------------------------------------
// 本文 4節：reduce（src/session10/reduce-basics.ts）
// ---------------------------------------------------------------------------
const bodyPrices = [480, 1800, 2350];
checkNumber(
  '本文4節: 価格の合計',
  bodyPrices.reduce((total, price) => total + price, 0),
  4630
);

// ステップ表の裏付け（各回の戻り値）
checkNumber('本文4節: 1回目の戻り値', 0 + 480, 480);
checkNumber('本文4節: 2回目の戻り値', 480 + 1800, 2280);
checkNumber('本文4節: 3回目の戻り値', 2280 + 2350, 4630);

const bodyCart = [
  { name: 'ラベンダーの石けん', price: 480, quantity: 2 },
  { name: 'ハンドクリーム', price: 1800, quantity: 1 },
];

checkNumber('本文4節: カートの小計', calcSubtotal(bodyCart), 2760);
checkNumber('本文4節: 空のカートの小計', calcSubtotal([]), 0);
checkNumber('本文4節: カートのステップ1', 0 + 480 * 2, 960);
checkNumber('本文4節: カートのステップ2', 960 + 1800 * 1, 2760);

function bodyReduceVariations(): string {
  const totalQuantity = bodyCart.reduce((total, line) => total + line.quantity, 0);
  const maxPrice = products.reduce(
    (max, product) => (product.price > max ? product.price : max),
    0
  );
  const soldOutCount = products.reduce(
    (count, product) => (product.stock === 0 ? count + 1 : count),
    0
  );
  return `合計${totalQuantity}点 / 最高単価${maxPrice}円 / 在庫切れ${soldOutCount}件`;
}

checkString(
  '本文4節: 合計以外の reduce',
  bodyReduceVariations(),
  '合計3点 / 最高単価2800円 / 在庫切れ1件'
);

// Bad（初期値なし）：空配列で TypeError になる
function bodyBadReduce(): string {
  const sumPrices = (prices: number[]): number => prices.reduce((total, price) => total + price);

  const withItems = sumPrices([480, 1800]);
  let emptyResult = '';
  try {
    emptyResult = String(sumPrices([]));
  } catch (error) {
    if (error instanceof TypeError && error.message.includes('Reduce of empty array')) {
      emptyResult = 'TypeError: Reduce of empty array';
    } else {
      emptyResult = '想定外のエラー';
    }
  }
  return `${withItems}\n${emptyResult}`;
}

checkString(
  '本文4節 Bad: 初期値を省略した reduce',
  bodyBadReduce(),
  '2280\nTypeError: Reduce of empty array'
);

// Good（初期値あり）：空配列でも 0 が返る
function bodyGoodReduce(): string {
  const sumPrices = (prices: number[]): number => prices.reduce((total, price) => total + price, 0);
  return `${sumPrices([480, 1800])}\n${sumPrices([])}`;
}

checkString('本文4節 Good: 初期値を書いた reduce', bodyGoodReduce(), '2280\n0');

// ---------------------------------------------------------------------------
// 本文 5節：toSorted と sort（src/session10/sort-basics.ts / sort-mutate.ts）
// ---------------------------------------------------------------------------
function bodyCompareFunction(): string {
  const stocks = [10, 9, 100];
  return (
    `比較関数なし: ${stocks.toSorted().join(' / ')}\n` +
    `比較関数あり: ${stocks.toSorted((a, b) => a - b).join(' / ')}`
  );
}

checkString(
  '本文5節: 比較関数の有無',
  bodyCompareFunction(),
  '比較関数なし: 10 / 100 / 9\n比較関数あり: 9 / 10 / 100'
);

function bodySortByPrice(): string {
  const byPriceAsc = products.toSorted((a, b) => a.price - b.price);
  const byPriceDesc = products.toSorted((a, b) => b.price - a.price);

  const lines: string[] = [];
  lines.push(`安い順: ${byPriceAsc.map((product) => product.name).join(' / ')}`);
  lines.push(`高い順: ${byPriceDesc.map((product) => product.name).join(' / ')}`);
  lines.push(`元の並び: ${products.map((product) => product.name).join(' / ')}`);
  return lines.join('\n');
}

checkString(
  '本文5節: 価格で並べ替える',
  bodySortByPrice(),
  '安い順: ラベンダーの石けん / リネンのふきん / ハンドクリーム / マグカップ / コットンのトートバッグ\n' +
    '高い順: コットンのトートバッグ / マグカップ / ハンドクリーム / リネンのふきん / ラベンダーの石けん\n' +
    '元の並び: ラベンダーの石けん / ハンドクリーム / マグカップ / リネンのふきん / コットンのトートバッグ'
);

function bodySortTwoKeys(): string {
  const grouped = products.toSorted((a, b) =>
    a.categoryId !== b.categoryId ? a.categoryId - b.categoryId : b.price - a.price
  );
  return grouped
    .map((product) => `${product.categoryId}:${product.name}:${product.price}`)
    .join('\n');
}

checkString(
  '本文5節: 2つのキーで並べ替える',
  bodySortTwoKeys(),
  '1:ハンドクリーム:1800\n' +
    '1:ラベンダーの石けん:480\n' +
    '2:マグカップ:2350\n' +
    '3:コットンのトートバッグ:2800\n' +
    '3:リネンのふきん:990'
);

function bodySortIsDestructive(): string {
  const prices = [2350, 480, 1800];
  const sortedCopy = [...prices].sort((a, b) => a - b);

  const lines: string[] = [];
  lines.push(`元: ${prices.join(' / ')}`);
  lines.push(`コピーを並べ替え: ${sortedCopy.join(' / ')}`);

  prices.sort((a, b) => a - b);
  lines.push(`直接 sort した後の元: ${prices.join(' / ')}`);
  return lines.join('\n');
}

checkString(
  '本文5節: sort は破壊的',
  bodySortIsDestructive(),
  '元: 2350 / 480 / 1800\nコピーを並べ替え: 480 / 1800 / 2350\n直接 sort した後の元: 480 / 1800 / 2350'
);

// ---------------------------------------------------------------------------
// 本文 6節：メソッドチェーン（src/session10/chain.ts）
// ---------------------------------------------------------------------------
function bodyChain(): string {
  const bathBodyStockValue = products
    .filter((product) => product.categoryId === 1)
    .reduce((total, product) => total + product.price * product.stock, 0);

  const stockReport = products
    .filter((product) => product.stock > 0)
    .toSorted((a, b) => b.price - a.price)
    .map((product) => `${product.name}：${product.price}円 × ${product.stock}点`);

  return `バス・ボディケアの在庫金額: ${bathBodyStockValue}円\n${stockReport.join('\n')}`;
}

checkString(
  '本文6節: メソッドチェーン',
  bodyChain(),
  'バス・ボディケアの在庫金額: 33120円\n' +
    'コットンのトートバッグ：2800円 × 5点\n' +
    'マグカップ：2350円 × 3点\n' +
    'ハンドクリーム：1800円 × 12点\n' +
    'ラベンダーの石けん：480円 × 24点'
);

checkNumber('本文6節: 在庫金額の内訳（石けん）', 480 * 24, 11520);
checkNumber('本文6節: 在庫金額の内訳（ハンドクリーム）', 1800 * 12, 21600);
checkNumber('本文6節: バス・ボディケアの合計', 11520 + 21600, 33120);

// Bad/Good（bad-chain.ts / good-chain.ts）は同じ結果になる
function bodyBadChain(): string {
  return products
    .filter((p) => p.stock > 0)
    .filter((p) => p.price >= 1000)
    .toSorted((a, b) => b.price * b.stock - a.price * a.stock)
    .map((p) => `${p.name}：${p.price * p.stock}円`)
    .join(' / ');
}

function bodyGoodChain(): string {
  const sellableProducts = products.filter((product) => product.stock > 0);
  const highPriceProducts = sellableProducts.filter((product) => product.price >= 1000);

  const byStockValueDesc = highPriceProducts.toSorted(
    (a, b) => b.price * b.stock - a.price * a.stock
  );

  const lines = byStockValueDesc.map(
    (product) => `${product.name}：${product.price * product.stock}円`
  );

  return lines.join(' / ');
}

checkString(
  '本文6節 Bad: 長いチェーン',
  bodyBadChain(),
  'ハンドクリーム：21600円 / コットンのトートバッグ：14000円 / マグカップ：7050円'
);
checkString('本文6節 Good: 名前を付けて切る', bodyGoodChain(), bodyBadChain());

// ---------------------------------------------------------------------------
// 本文 7節：Map（src/session10/map-object.ts）
// ---------------------------------------------------------------------------
/** カテゴリID → カテゴリ名 の Map を作る */
function buildCategoryNameById(): Map<number, string> {
  const map = new Map<number, string>();
  for (const category of categories) {
    map.set(category.id, category.name);
  }
  return map;
}

/** 商品ID → 商品オブジェクト の Map を作る（本文と同じ長い型を書く） */
function buildProductById(): Map<
  number,
  { id: number; name: string; price: number; stock: number; categoryId: number }
> {
  const map = new Map<
    number,
    { id: number; name: string; price: number; stock: number; categoryId: number }
  >();
  for (const product of products) {
    map.set(product.id, product);
  }
  return map;
}

function bodyMapBasics(): string {
  const categoryNameById = buildCategoryNameById();

  const lines: string[] = [];
  lines.push(`件数: ${categoryNameById.size}`);
  lines.push(`id=2: ${categoryNameById.get(2)}`);
  lines.push(`id=99: ${categoryNameById.get(99)}`);
  lines.push(`id=3 はある: ${categoryNameById.has(3)}`);
  return lines.join('\n');
}

checkString(
  '本文7節: Map の基本操作',
  bodyMapBasics(),
  '件数: 3\nid=2: キッチン雑貨\nid=99: undefined\nid=3 はある: true'
);

// 最初から中身を入れて作る形
const bodyCategoryNameByIdLiteral = new Map<number, string>([
  [1, 'バス・ボディケア'],
  [2, 'キッチン雑貨'],
  [3, 'ファブリック'],
]);
checkNumber('本文7節: リテラルから作った Map の件数', bodyCategoryNameByIdLiteral.size, 3);

// get の戻り値は「値 または undefined」
checkString('本文7節: get の既定値', buildCategoryNameById().get(4) ?? '(未分類)', '(未分類)');

function bodyMapIteration(): string {
  const categoryNameById = buildCategoryNameById();

  const lines: string[] = [];
  for (const [id, name] of categoryNameById) {
    lines.push(`${id}: ${name}`);
  }
  lines.push(`キー: ${[...categoryNameById.keys()].join(' / ')}`);
  lines.push(`値: ${[...categoryNameById.values()].join(' / ')}`);
  return lines.join('\n');
}

checkString(
  '本文7節: Map の走査（挿入順が保たれる）',
  bodyMapIteration(),
  '1: バス・ボディケア\n' +
    '2: キッチン雑貨\n' +
    '3: ファブリック\n' +
    'キー: 1 / 2 / 3\n' +
    '値: バス・ボディケア / キッチン雑貨 / ファブリック'
);

function bodyProductById(): string {
  const productById = buildProductById();

  const lines: string[] = [];
  const target = productById.get(3);
  if (target === undefined) {
    lines.push('該当する商品がありません');
  } else {
    lines.push(`${target.name}：${target.price}円`);
  }
  lines.push(`削除できた: ${productById.delete(4)} / 残り${productById.size}件`);
  return lines.join('\n');
}

checkString(
  '本文7節: id から商品を引く Map',
  bodyProductById(),
  'マグカップ：2350円\n削除できた: true / 残り4件'
);

// 存在しないキーの delete は false
checkBoolean('本文7節: 無いキーの delete', buildProductById().delete(99), false);

// ---------------------------------------------------------------------------
// 本文 8節：Set（src/session10/set-basics.ts / set-object.ts）
// ---------------------------------------------------------------------------
function bodySetBasics(): string {
  const tags = new Set<string>();
  tags.add('ギフト');
  tags.add('新入荷');
  tags.add('ギフト'); // すでにあるので増えない

  const lines: string[] = [];
  lines.push(`件数: ${tags.size}`);
  lines.push(`ギフトを含む: ${tags.has('ギフト')}`);
  lines.push(`一覧: ${[...tags].join(' / ')}`);
  return lines.join('\n');
}

checkString(
  '本文8節: Set の基本操作',
  bodySetBasics(),
  '件数: 2\nギフトを含む: true\n一覧: ギフト / 新入荷'
);

checkString('本文8節: 数値の重複排除', [...new Set([1, 2, 1, 5])].join(' / '), '1 / 2 / 5');

function bodyOrderedCategories(): string {
  const categoryNameById = buildCategoryNameById();
  const productById = buildProductById();

  const orderedProductIds = [1, 2, 1, 5];

  const orderedCategoryNames = orderedProductIds.map((productId) => {
    const product = productById.get(productId);
    if (product === undefined) {
      return '(不明な商品)';
    }
    return categoryNameById.get(product.categoryId) ?? '(未分類)';
  });

  const uniqueCategoryNames = [...new Set(orderedCategoryNames)];

  return (
    `重複あり（${orderedCategoryNames.length}件）: ${orderedCategoryNames.join(' / ')}\n` +
    `重複なし（${uniqueCategoryNames.length}件）: ${uniqueCategoryNames.join(' / ')}`
  );
}

checkString(
  '本文8節: 注文カテゴリの重複排除',
  bodyOrderedCategories(),
  '重複あり（4件）: バス・ボディケア / バス・ボディケア / バス・ボディケア / ファブリック\n' +
    '重複なし（2件）: バス・ボディケア / ファブリック'
);

function bodySetOfObjects(): string {
  const lineA = { name: 'マグカップ', quantity: 1 };
  const lineB = { name: 'マグカップ', quantity: 1 };

  const lines = new Set([lineA, lineB, lineA]);
  const uniqueNames = [...new Set([lineA, lineB, lineA].map((line) => line.name))];

  return `件数: ${lines.size}\n${uniqueNames.join(' / ')}`;
}

checkString(
  '本文8節: オブジェクトは参照で判定される',
  bodySetOfObjects(),
  '件数: 2\nマグカップ'
);

// よくある誤解の裏付け
checkNumber('誤解の確認: 中身が同じオブジェクトの Set', new Set([{ id: 1 }, { id: 1 }]).size, 2);

// ---------------------------------------------------------------------------
// 本文 9節：Object.keys / values / entries（src/session10/object-entries.ts）
// ---------------------------------------------------------------------------
const CATEGORY_NAME_BY_SLUG = {
  'bath-body': 'バス・ボディケア',
  kitchen: 'キッチン雑貨',
  fabric: 'ファブリック',
};

function bodyObjectEntries(): string {
  const lines: string[] = [];
  lines.push(`キー: ${Object.keys(CATEGORY_NAME_BY_SLUG).join(' / ')}`);
  lines.push(`値: ${Object.values(CATEGORY_NAME_BY_SLUG).join(' / ')}`);
  for (const [slug, name] of Object.entries(CATEGORY_NAME_BY_SLUG)) {
    lines.push(`${slug} → ${name}`);
  }
  return lines.join('\n');
}

checkString(
  '本文9節: Object.keys / values / entries',
  bodyObjectEntries(),
  'キー: bath-body / kitchen / fabric\n' +
    '値: バス・ボディケア / キッチン雑貨 / ファブリック\n' +
    'bath-body → バス・ボディケア\n' +
    'kitchen → キッチン雑貨\n' +
    'fabric → ファブリック'
);

checkString(
  '本文9節: entries を map につなぐ',
  Object.entries(CATEGORY_NAME_BY_SLUG)
    .map(([slug, name]) => `${slug}=${name}`)
    .join(' / '),
  'bath-body=バス・ボディケア / kitchen=キッチン雑貨 / fabric=ファブリック'
);

function bodyNumericKeys(): string {
  const stockByProductId = { 1: 24, 2: 12, 3: 3 };

  const lines: string[] = [];
  lines.push(`キー: ${Object.keys(stockByProductId).join(' / ')}`);
  lines.push(`キーの型: ${typeof Object.keys(stockByProductId)[0]}`);
  lines.push(
    `在庫の合計: ${Object.values(stockByProductId).reduce((total, stock) => total + stock, 0)}`
  );
  return lines.join('\n');
}

checkString(
  '本文9節: 数値キーは文字列になる',
  bodyNumericKeys(),
  'キー: 1 / 2 / 3\nキーの型: string\n在庫の合計: 39'
);

// ---------------------------------------------------------------------------
// 本文 10節：総合（src/session10/stock-report.ts）
// ---------------------------------------------------------------------------
function bodyReportByFilter(): string {
  return categories
    .map((category) => {
      const items = products.filter((product) => product.categoryId === category.id);
      const inStockCount = items.filter((item) => item.stock > 0).length;
      const summary = `商品${items.length}点 / 在庫あり${inStockCount}点`;
      return `${category.name}：${sumStockValue(items)}円（${summary}）`;
    })
    .join('\n');
}

checkString(
  '本文10節 方法A: filter → reduce',
  bodyReportByFilter(),
  'バス・ボディケア：33120円（商品2点 / 在庫あり2点）\n' +
    'キッチン雑貨：7050円（商品1点 / 在庫あり1点）\n' +
    'ファブリック：14000円（商品2点 / 在庫あり1点）'
);

/** 方法B：products を1周して Map に足し込む */
function buildStockValueByCategoryId(): Map<number, number> {
  const stockValueByCategoryId = new Map<number, number>();
  for (const product of products) {
    const current = stockValueByCategoryId.get(product.categoryId) ?? 0;
    stockValueByCategoryId.set(product.categoryId, current + product.price * product.stock);
  }
  return stockValueByCategoryId;
}

function bodyReportByMap(): string {
  const stockValueByCategoryId = buildStockValueByCategoryId();

  const reportByMap = categories.map(
    (category) => `${category.name}：${stockValueByCategoryId.get(category.id) ?? 0}円`
  );

  const totalStockValue = [...stockValueByCategoryId.values()].reduce(
    (total, value) => total + value,
    0
  );

  return `${reportByMap.join('\n')}\n全体: ${totalStockValue}円`;
}

checkString(
  '本文10節 方法B: Map で1周',
  bodyReportByMap(),
  'バス・ボディケア：33120円\nキッチン雑貨：7050円\nファブリック：14000円\n全体: 54170円'
);

checkNumber('本文10節: 全体の在庫金額', sumStockValue(products), 54170);

// ---------------------------------------------------------------------------
// 問題1：map と filter で商品リストを加工する
// ---------------------------------------------------------------------------
function solveQ1(): string {
  const numberedLines = products.map(
    (product, index) => `${index + 1}. ${product.name}（${product.price}円）`
  );

  const inStockNames = products
    .filter((product) => product.stock > 0)
    .map((product) => product.name);

  const highPriceLabels = products
    .filter((product) => product.price >= 1000)
    .map((product) => `${product.name}:${product.price}`);

  const lines: string[] = [];
  lines.push(numberedLines.join('\n'));
  lines.push(`在庫あり: ${inStockNames.join(' / ')}`);
  lines.push(`1000円以上: ${highPriceLabels.join(' / ')}`);
  lines.push(`元の商品数: ${products.length}点`);
  return lines.join('\n');
}

const q1Expected =
  '1. ラベンダーの石けん（480円）\n' +
  '2. ハンドクリーム（1800円）\n' +
  '3. マグカップ（2350円）\n' +
  '4. リネンのふきん（990円）\n' +
  '5. コットンのトートバッグ（2800円）\n' +
  '在庫あり: ラベンダーの石けん / ハンドクリーム / マグカップ / コットンのトートバッグ\n' +
  '1000円以上: ハンドクリーム:1800 / マグカップ:2350 / コットンのトートバッグ:2800\n' +
  '元の商品数: 5点';

checkString('問題1: 出力8行', solveQ1(), q1Expected);

// 問題1 別解：チェーンを2行に分ける（出力は同じ）
function solveQ1Alternative(): string {
  const inStockProducts = products.filter((product) => product.stock > 0);
  const inStockNames = inStockProducts.map((product) => product.name);
  return `在庫あり: ${inStockNames.join(' / ')}`;
}

checkString(
  '問題1 別解: 中間変数に名前を付ける',
  solveQ1Alternative(),
  '在庫あり: ラベンダーの石けん / ハンドクリーム / マグカップ / コットンのトートバッグ'
);

// ---------------------------------------------------------------------------
// 問題2：find / some / every で在庫を判定する
// ---------------------------------------------------------------------------
const describeProductById = (
  items: { id: number; name: string; price: number }[],
  id: number
): string => {
  const product = items.find((item) => item.id === id);

  if (product === undefined) {
    return '該当する商品がありません';
  }

  return `${product.name}（${product.price}円）`;
};

function solveQ2(): string {
  const lines: string[] = [];
  lines.push(`id=3: ${describeProductById(products, 3)}`);
  lines.push(`id=99: ${describeProductById(products, 99)}`);

  const soldOutProduct = products.find((product) => product.stock === 0);
  if (soldOutProduct === undefined) {
    lines.push('在庫切れ: なし');
  } else {
    lines.push(`在庫切れ: ${soldOutProduct.name}`);
  }

  lines.push(`在庫切れの商品がある: ${products.some((product) => product.stock === 0)}`);
  lines.push(`すべて在庫がある: ${products.every((product) => product.stock > 0)}`);

  const emptyProducts: { stock: number }[] = [];
  lines.push(
    `空配列の some: ${emptyProducts.some((product) => product.stock > 0)} / ` +
      `every: ${emptyProducts.every((product) => product.stock > 0)}`
  );
  return lines.join('\n');
}

checkString(
  '問題2: 出力6行',
  solveQ2(),
  'id=3: マグカップ（2350円）\n' +
    'id=99: 該当する商品がありません\n' +
    '在庫切れ: リネンのふきん\n' +
    '在庫切れの商品がある: true\n' +
    'すべて在庫がある: false\n' +
    '空配列の some: false / every: true'
);

// 選択問題(B) の裏付け：空配列の every は true
const q2EmptyProducts: { stock: number }[] = [];
checkBoolean('問題2 選択問題(B): 空配列の every', q2EmptyProducts.every((p) => p.stock > 0), true);

// ---------------------------------------------------------------------------
// 問題3：reduce でカートの支払総額を出す
// ---------------------------------------------------------------------------
const q3Cart = [
  { name: 'ラベンダーの石けん', price: 480, quantity: 2 },
  { name: 'ハンドクリーム', price: 1800, quantity: 1 },
  { name: 'コットンのトートバッグ', price: 2800, quantity: 1 },
];

function solveQ3(): string {
  const noDiscount = (): number => 0;
  const bronzeRule = makePercentDiscount(3);

  const lineTexts = q3Cart.map(
    (line) => `${line.name} ${line.price}円 × ${line.quantity}点 = ${line.price * line.quantity}円`
  );

  const subtotal = calcSubtotal(q3Cart);
  const totalQuantity = q3Cart.reduce((total, line) => total + line.quantity, 0);
  const maxPrice = q3Cart.reduce((max, line) => (line.price > max ? line.price : max), 0);

  const emptyCart: { price: number; quantity: number }[] = [];

  const lines: string[] = [];
  lines.push(lineTexts.join('\n'));
  lines.push(`明細${q3Cart.length}件 / 合計${totalQuantity}点 / 小計${subtotal}円`);
  lines.push(`最高単価: ${maxPrice}円`);
  lines.push(`割引なし: お支払い${calcPayableAmount(subtotal, noDiscount)}円`);
  lines.push(`ブロンズ3%: お支払い${calcPayableAmount(subtotal, bronzeRule)}円`);
  lines.push(`空のカート: 小計${calcSubtotal(emptyCart)}円`);
  return lines.join('\n');
}

checkString(
  '問題3: 出力8行',
  solveQ3(),
  'ラベンダーの石けん 480円 × 2点 = 960円\n' +
    'ハンドクリーム 1800円 × 1点 = 1800円\n' +
    'コットンのトートバッグ 2800円 × 1点 = 2800円\n' +
    '明細3件 / 合計4点 / 小計5560円\n' +
    '最高単価: 2800円\n' +
    '割引なし: お支払い6116円\n' +
    'ブロンズ3%: お支払い5933円\n' +
    '空のカート: 小計0円'
);

// 計算手順の1ステップずつの検算（解答の説明に書いた数値）
checkNumber('問題3 手順1 小計', calcSubtotal(q3Cart), 5560);
checkNumber('問題3 割引なしの消費税', Math.floor(5560 * TAX_RATE), 556);
checkNumber('問題3 割引なしの税込商品合計', 5560 + 556, 6116);
checkNumber('問題3 ブロンズの割引額', makePercentDiscount(3)(5560), 166);
checkNumber('問題3 ブロンズの割引後小計', 5560 - 166, 5394);
checkNumber('問題3 ブロンズの消費税', Math.floor(5394 * TAX_RATE), 539);
checkNumber('問題3 ブロンズの税込商品合計', 5394 + 539, 5933);
checkNumber('問題3 送料（割引なし）', calcShippingFee(6116), 0);
checkNumber('問題3 送料（ブロンズ）', calcShippingFee(5933), 0);

// 問題3 別解：Math.max とスプレッド構文（空配列だと -Infinity になる）
const q3EmptyPrices: number[] = [];
checkNumber(
  '問題3 別解: Math.max で最高単価',
  Math.max(...q3Cart.map((line) => line.price)),
  2800
);
checkBoolean(
  '問題3 別解: 空配列だと -Infinity',
  Math.max(...q3EmptyPrices) === Number.NEGATIVE_INFINITY,
  true
);

// ---------------------------------------------------------------------------
// 問題4：toSorted で並べ替える
// ---------------------------------------------------------------------------
function solveQ4(): string {
  const stocks = [10, 9, 100];

  const byPriceAsc = products.toSorted((a, b) => a.price - b.price);
  const byPriceDesc = products.toSorted((a, b) => b.price - a.price);

  const grouped = products.toSorted((a, b) =>
    a.categoryId !== b.categoryId ? a.categoryId - b.categoryId : b.price - a.price
  );

  const firstProduct = products[0];

  const prices = [2350, 480, 1800];
  const sortedCopy = [...prices].sort((a, b) => a - b);

  const lines: string[] = [];
  lines.push(`比較関数なし: ${stocks.toSorted().join(' / ')}`);
  lines.push(`比較関数あり: ${stocks.toSorted((a, b) => a - b).join(' / ')}`);
  lines.push(`安い順: ${byPriceAsc.map((product) => product.name).join(' / ')}`);
  lines.push(`高い順: ${byPriceDesc.map((product) => product.name).join(' / ')}`);
  lines.push(
    grouped.map((product) => `${product.categoryId}:${product.name}:${product.price}`).join('\n')
  );
  lines.push(`元の先頭: ${firstProduct === undefined ? '(商品なし)' : firstProduct.name}`);
  lines.push(`コピーを sort: 元 ${prices.join(' / ')} → 並べ替え ${sortedCopy.join(' / ')}`);

  prices.sort((a, b) => a - b);
  lines.push(`元を直接 sort: ${prices.join(' / ')}`);
  return lines.join('\n');
}

checkString(
  '問題4: 出力12行',
  solveQ4(),
  '比較関数なし: 10 / 100 / 9\n' +
    '比較関数あり: 9 / 10 / 100\n' +
    '安い順: ラベンダーの石けん / リネンのふきん / ハンドクリーム / マグカップ / コットンのトートバッグ\n' +
    '高い順: コットンのトートバッグ / マグカップ / ハンドクリーム / リネンのふきん / ラベンダーの石けん\n' +
    '1:ハンドクリーム:1800\n' +
    '1:ラベンダーの石けん:480\n' +
    '2:マグカップ:2350\n' +
    '3:コットンのトートバッグ:2800\n' +
    '3:リネンのふきん:990\n' +
    '元の先頭: ラベンダーの石けん\n' +
    'コピーを sort: 元 2350 / 480 / 1800 → 並べ替え 480 / 1800 / 2350\n' +
    '元を直接 sort: 480 / 1800 / 2350'
);

// 安定ソートの確認（同じ比較結果の要素の順序は保たれる）
const q4SameCategory = products
  .filter((product) => product.categoryId === 3)
  .toSorted((a, b) => a.categoryId - b.categoryId)
  .map((product) => product.name)
  .join(' / ');
checkString('問題4: 安定ソート', q4SameCategory, 'リネンのふきん / コットンのトートバッグ');

// ---------------------------------------------------------------------------
// 問題5：Map と Set で注文を集計する
// ---------------------------------------------------------------------------
const q5OrderItems = [
  { productId: 1, quantity: 2 },
  { productId: 3, quantity: 1 },
  { productId: 1, quantity: 1 },
  { productId: 5, quantity: 1 },
];

function solveQ5(): string {
  const productNameById = new Map<number, string>();
  const categoryIdByProductId = new Map<number, number>();

  for (const product of products) {
    productNameById.set(product.id, product.name);
    categoryIdByProductId.set(product.id, product.categoryId);
  }

  const categoryNameById = new Map<number, string>();
  for (const category of categories) {
    categoryNameById.set(category.id, category.name);
  }

  const lines: string[] = [];
  lines.push(
    `商品マスタ: ${productNameById.size}件 / id=3 → ${productNameById.get(3)} / ` +
      `id=99 → ${productNameById.get(99)}`
  );

  const quantityByProductId = new Map<number, number>();
  for (const item of q5OrderItems) {
    const current = quantityByProductId.get(item.productId) ?? 0;
    quantityByProductId.set(item.productId, current + item.quantity);
  }

  for (const [productId, quantity] of quantityByProductId) {
    lines.push(`${productNameById.get(productId) ?? '(不明な商品)'} × ${quantity}点`);
  }

  const orderedCategoryNames = q5OrderItems.map((item) => {
    const categoryId = categoryIdByProductId.get(item.productId);
    if (categoryId === undefined) {
      return '(不明な商品)';
    }
    return categoryNameById.get(categoryId) ?? '(未分類)';
  });

  const uniqueCategoryNames = [...new Set(orderedCategoryNames)];

  lines.push(
    `注文カテゴリ（重複あり${orderedCategoryNames.length}件）: ${orderedCategoryNames.join(' / ')}`
  );
  lines.push(
    `注文カテゴリ（重複なし${uniqueCategoryNames.length}件）: ${uniqueCategoryNames.join(' / ')}`
  );

  for (const [slug, name] of Object.entries(CATEGORY_NAME_BY_SLUG)) {
    lines.push(`${slug} → ${name}`);
  }
  return lines.join('\n');
}

checkString(
  '問題5: 出力9行',
  solveQ5(),
  '商品マスタ: 5件 / id=3 → マグカップ / id=99 → undefined\n' +
    'ラベンダーの石けん × 3点\n' +
    'マグカップ × 1点\n' +
    'コットンのトートバッグ × 1点\n' +
    '注文カテゴリ（重複あり4件）: バス・ボディケア / キッチン雑貨 / バス・ボディケア / ファブリック\n' +
    '注文カテゴリ（重複なし3件）: バス・ボディケア / キッチン雑貨 / ファブリック\n' +
    'bath-body → バス・ボディケア\n' +
    'kitchen → キッチン雑貨\n' +
    'fabric → ファブリック'
);

// 同じキーに set をし直しても Map の順番は変わらない（解答④の裏付け）
const q5Order = new Map<number, number>();
q5Order.set(1, 2);
q5Order.set(3, 1);
q5Order.set(1, 3);
q5Order.set(5, 1);
checkString('問題5: Map は挿入順を保つ', [...q5Order.keys()].join(' / '), '1 / 3 / 5');

// ---------------------------------------------------------------------------
// 問題6：カテゴリ別の在庫レポートを2通りで作る
// ---------------------------------------------------------------------------
function solveQ6(): string {
  const categoryNameById = buildCategoryNameById();

  const reportByFilter = categories.map((category) => {
    const items = products.filter((product) => product.categoryId === category.id);
    const inStockCount = items.filter((item) => item.stock > 0).length;
    const summary = `商品${items.length}点 / 在庫あり${inStockCount}点`;
    return `[方法A] ${category.name}：${sumStockValue(items)}円（${summary}）`;
  });

  const stockValueByCategoryId = buildStockValueByCategoryId();

  const reportByMap = categories.map(
    (category) => `[方法B] ${category.name}：${stockValueByCategoryId.get(category.id) ?? 0}円`
  );

  const totalByFilter = sumStockValue(products);
  const totalByMap = [...stockValueByCategoryId.values()].reduce((total, value) => total + value, 0);

  const soldOutNames = products
    .filter((product) => product.stock === 0)
    .map((product) => product.name);

  const ranked = [...stockValueByCategoryId].toSorted((a, b) => b[1] - a[1]);
  const top = ranked[0];

  const lines: string[] = [];
  lines.push(reportByFilter.join('\n'));
  lines.push(reportByMap.join('\n'));
  lines.push(
    `合計: 方法A ${totalByFilter}円 / 方法B ${totalByMap}円（一致: ${totalByFilter === totalByMap}）`
  );
  lines.push(`在庫切れ: ${soldOutNames.join(' / ')}`);

  if (top === undefined) {
    lines.push('在庫金額が最大: (データがありません)');
  } else {
    lines.push(`在庫金額が最大: ${categoryNameById.get(top[0]) ?? '(未分類)'}（${top[1]}円）`);
  }
  return lines.join('\n');
}

const q6Expected =
  '[方法A] バス・ボディケア：33120円（商品2点 / 在庫あり2点）\n' +
  '[方法A] キッチン雑貨：7050円（商品1点 / 在庫あり1点）\n' +
  '[方法A] ファブリック：14000円（商品2点 / 在庫あり1点）\n' +
  '[方法B] バス・ボディケア：33120円\n' +
  '[方法B] キッチン雑貨：7050円\n' +
  '[方法B] ファブリック：14000円\n' +
  '合計: 方法A 54170円 / 方法B 54170円（一致: true）\n' +
  '在庫切れ: リネンのふきん\n' +
  '在庫金額が最大: バス・ボディケア（33120円）';

checkString('問題6: 出力9行', solveQ6(), q6Expected);

// 在庫金額の内訳（解答の表に書いた数値）
checkNumber('問題6: マグカップの在庫金額', 2350 * 3, 7050);
checkNumber('問題6: リネンのふきんの在庫金額', 990 * 0, 0);
checkNumber('問題6: トートバッグの在庫金額', 2800 * 5, 14000);
checkNumber('問題6: 全体の在庫金額', 33120 + 7050 + 14000, 54170);

// 問題6 別解：reduce の中で Map に足し込む（結果は模範解答と同じ）
function solveQ6Alternative(): string {
  const stockValueByCategoryId = products.reduce((acc, product) => {
    const current = acc.get(product.categoryId) ?? 0;
    acc.set(product.categoryId, current + product.price * product.stock);
    return acc;
  }, new Map<number, number>());

  return categories
    .map((category) => `[方法B] ${category.name}：${stockValueByCategoryId.get(category.id) ?? 0}円`)
    .join('\n');
}

checkString(
  '問題6 別解: reduce で Map に集計',
  solveQ6Alternative(),
  '[方法B] バス・ボディケア：33120円\n[方法B] キッチン雑貨：7050円\n[方法B] ファブリック：14000円'
);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session10: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session10: ok');
