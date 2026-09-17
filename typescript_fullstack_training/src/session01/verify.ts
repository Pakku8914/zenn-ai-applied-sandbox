/**
 * セッション1「TypeScriptとは・変数・データ型」のコード例を検証する。
 * 章本文・練習問題・解答に載せた「期待される出力」と一致しなければ非0終了する。
 */

/** console.log に渡せる基本型の値 */
type LogValue = string | number | boolean | null | undefined;

/** console.log と同じ整形規則（引数を半角スペースでつなぐ）で1行を組み立てる */
const line = (...parts: LogValue[]): string => parts.map((part) => String(part)).join(' ');

const failures: string[] = [];

const check = (label: string, actual: string, expected: string): void => {
  if (actual !== expected) {
    failures.push(`${label}\n    期待値: ${JSON.stringify(expected)}\n    実際  : ${JSON.stringify(actual)}`);
  }
};

// ---------------------------------------------------------------------------
// 1. 本文 src/session01/product-info.ts の出力
// ---------------------------------------------------------------------------
const productName = 'マグカップ';
const price = 1200;
const stock = 12;
const isOnSale = true;

check(
  'product-info.ts',
  [
    line('商品名:', productName),
    line('価格:', price, '円'),
    line('在庫:', stock, '個'),
    line('セール中:', isOnSale),
  ].join('\n'),
  ['商品名: マグカップ', '価格: 1200 円', '在庫: 12 個', 'セール中: true'].join('\n'),
);

// ---------------------------------------------------------------------------
// 2. 本文 src/session01/stock-update.ts の出力（let による再代入）
// ---------------------------------------------------------------------------
let updatedStock = 12;
const stockUpdateLines: string[] = [];
stockUpdateLines.push(productName + 'の在庫: ' + updatedStock);
updatedStock = 11; // 1個売れた
stockUpdateLines.push('1個売れました');
stockUpdateLines.push(productName + 'の在庫: ' + updatedStock);

check(
  'stock-update.ts',
  stockUpdateLines.join('\n'),
  ['マグカップの在庫: 12', '1個売れました', 'マグカップの在庫: 11'].join('\n'),
);

// ---------------------------------------------------------------------------
// 3. 本文 src/session01/type-annotation.ts の出力（typeof / null / undefined）
// ---------------------------------------------------------------------------
const annotatedName: string = 'マグカップ';
const annotatedPrice: number = 1200;
const annotatedStock: number = 12;
const annotatedIsOnSale: boolean = true;
const discontinuedNote: null = null;
const shippingDate: undefined = undefined;

check(
  'type-annotation.ts',
  [
    typeof annotatedName,
    typeof annotatedPrice,
    typeof annotatedIsOnSale,
    typeof shippingDate,
    typeof discontinuedNote,
    line('null を表示:', discontinuedNote),
    line('undefined を表示:', shippingDate),
    line('在庫:', annotatedStock),
  ].join('\n'),
  [
    'string',
    'number',
    'boolean',
    'undefined',
    'object',
    'null を表示: null',
    'undefined を表示: undefined',
    '在庫: 12',
  ].join('\n'),
);

// typeof null が 'object' であること（本文「よくある誤解」の根拠）
check('typeof null は object', typeof discontinuedNote, 'object');
check('typeof undefined は undefined', typeof shippingDate, 'undefined');

// ---------------------------------------------------------------------------
// 4. 問題1 src/session01/socks.ts の出力
// ---------------------------------------------------------------------------
const socksName = 'ソックス';
const socksPrice = 780;
const socksStock = 40;
const socksIsOnSale = false;

check(
  '問題1 socks.ts',
  [
    line('商品名:', socksName),
    line('価格:', socksPrice, '円'),
    line('在庫:', socksStock, '個'),
    line('セール中:', socksIsOnSale),
  ].join('\n'),
  ['商品名: ソックス', '価格: 780 円', '在庫: 40 個', 'セール中: false'].join('\n'),
);

// ---------------------------------------------------------------------------
// 5. 問題2 src/session01/annotation-practice.ts の出力
// ---------------------------------------------------------------------------
const categoryName: string = 'キッチン';
const shippingFee: number = 500;
const isFreeShipping: boolean = false;

let selectedProductName: string;
selectedProductName = 'ソックス';

check(
  '問題2 annotation-practice.ts',
  [
    line('カテゴリ:', categoryName),
    line('送料:', shippingFee, '円'),
    line('送料無料:', isFreeShipping),
    line('選択中の商品:', selectedProductName),
  ].join('\n'),
  [
    'カテゴリ: キッチン',
    '送料: 500 円',
    '送料無料: false',
    '選択中の商品: ソックス',
  ].join('\n'),
);

// ---------------------------------------------------------------------------
// 6. 問題3 src/session01/stock-log.ts の出力（const / let の振り分け）
// ---------------------------------------------------------------------------
const towelName = 'タオル';
const towelPrice = 980;
let towelStock = 5;
const stockLogLines: string[] = [];

stockLogLines.push(line(towelName + '（' + towelPrice + '円）の在庫:', towelStock, '個'));
towelStock = 3;
stockLogLines.push('2個売れました');
stockLogLines.push(line(towelName + '（' + towelPrice + '円）の在庫:', towelStock, '個'));
towelStock = 0;
stockLogLines.push('3個売れました');
stockLogLines.push(line(towelName + '（' + towelPrice + '円）の在庫:', towelStock, '個'));

check(
  '問題3 stock-log.ts',
  stockLogLines.join('\n'),
  [
    'タオル（980円）の在庫: 5 個',
    '2個売れました',
    'タオル（980円）の在庫: 3 個',
    '3個売れました',
    'タオル（980円）の在庫: 0 個',
  ].join('\n'),
);

// ---------------------------------------------------------------------------
// 7. 問題5 src/session01/predict.ts の出力
// ---------------------------------------------------------------------------
check(
  '問題5 predict.ts',
  [
    typeof categoryName,
    typeof shippingFee,
    typeof isFreeShipping,
    typeof discontinuedNote,
    typeof shippingDate,
    line('値の表示:', discontinuedNote, shippingDate),
  ].join('\n'),
  ['string', 'number', 'boolean', 'object', 'undefined', '値の表示: null undefined'].join('\n'),
);

// ---------------------------------------------------------------------------
// 8. 問題6 src/session01/review-fixed.ts の出力（var を排除した形）
// ---------------------------------------------------------------------------
let reviewProductName = 'マグカップ';
const reviewPrice = 1200;
let reviewStock = 12;
const reviewLines: string[] = [];

reviewLines.push(line(reviewProductName, reviewPrice, reviewStock));
reviewStock = 11;
reviewProductName = 'マグカップ（新パッケージ）';
reviewLines.push(line(reviewProductName, reviewPrice, reviewStock));

check(
  '問題6 review-fixed.ts',
  reviewLines.join('\n'),
  ['マグカップ 1200 12', 'マグカップ（新パッケージ） 1200 11'].join('\n'),
);

// ---------------------------------------------------------------------------
// 9. 問題7 src/session01/refactored.ts の出力（リファクタリング後も出力は同じ）
// ---------------------------------------------------------------------------
const refactoredName = 'タオル';
const refactoredPrice = 980;
const refactoredStock = 5;
const refactoredIsOnSale = true;
const refactoredNote: null = null;

check(
  '問題7 refactored.ts',
  [
    line(refactoredName, refactoredPrice, refactoredStock, refactoredIsOnSale, refactoredNote),
    refactoredName + 'は' + refactoredPrice + '円です',
  ].join('\n'),
  ['タオル 980 5 true null', 'タオルは980円です'].join('\n'),
);

// ---------------------------------------------------------------------------
// 10. 章で使った文字列結合の規則（数値は文字列に変換されて連結される）
// ---------------------------------------------------------------------------
check('数値と文字列の結合', 'マグカップ' + 'の在庫: ' + 12, 'マグカップの在庫: 12');

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failures.length > 0) {
  console.error('session01: 検証に失敗しました（' + failures.length + ' 件）');
  for (const failure of failures) {
    console.error('  - ' + failure);
  }
  process.exit(1);
}

console.log('session01: ok');
