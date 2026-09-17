/**
 * セッション4「繰り返し」の検証スクリプト。
 *
 * 本文（011）と練習問題の解答（013）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * console.log を1行ずつ出す章のコードは、この検証では
 * 「出力行を \n でつないだ文字列」を返す関数として表現している。
 *
 * 実行: docker compose exec ts npx tsx src/session04/verify.ts
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
// 本文 1節：while 文（src/session04/while-shipping.ts）
// ---------------------------------------------------------------------------

/** 在庫がある間、1個ずつ出荷する（while 版） */
function shipOneByOne(initialStock: number): string {
  let stock = initialStock;
  let log = '';

  while (stock > 0) {
    stock -= 1;
    log += `1個出荷しました。残りの在庫: ${stock}個\n`;
  }

  return `${log}在庫がなくなりました`;
}

checkString(
  '本文1節: 在庫3個の出荷ログ',
  shipOneByOne(3),
  '1個出荷しました。残りの在庫: 2個\n' +
    '1個出荷しました。残りの在庫: 1個\n' +
    '1個出荷しました。残りの在庫: 0個\n' +
    '在庫がなくなりました'
);
checkString('本文1節: 在庫0個なら0回（while）', shipOneByOne(0), '在庫がなくなりました');

// ---------------------------------------------------------------------------
// 本文 2節：do-while（src/session04/do-while-danger.ts / digit-count.ts）
// ---------------------------------------------------------------------------

/** do-while で書くと在庫0個でも1回出荷してしまう（本文の悪い例） */
function shipWithDoWhile(initialStock: number): string {
  let stock = initialStock;
  let log = '';

  do {
    stock -= 1;
    log += `1個出荷しました。残りの在庫: ${stock}個\n`;
  } while (stock > 0);

  return log;
}

/** 整数の桁数を返す（0 は「1桁」と数える） */
function countDigits(value: number): number {
  let rest = value;
  let digits = 0;

  do {
    rest = Math.floor(rest / 10);
    digits += 1;
  } while (rest > 0);

  return digits;
}

checkString(
  '本文2節: 在庫0個でも1回実行される（do-while）',
  shipWithDoWhile(0),
  '1個出荷しました。残りの在庫: -1個\n'
);
checkNumber('本文2節: countDigits(0)', countDigits(0), 1);
checkNumber('本文2節: countDigits(7)', countDigits(7), 1);
checkNumber('本文2節: countDigits(1800)', countDigits(1800), 4);
checkNumber('本文2節: countDigits(24)', countDigits(24), 2);

// ---------------------------------------------------------------------------
// 本文 3節：for 文（src/session04/for-basic.ts）
// ---------------------------------------------------------------------------
const bodyNames: string[] = ['ラベンダーの石けん', 'ハンドクリーム', 'マグカップ'];

/** 1から5まで数える */
function countUpLog(): string {
  let log = '';
  for (let i = 1; i <= 5; i++) {
    log += `${i}回目\n`;
  }
  return log;
}

/** 番号を付けて並びを表示する（番号が必要なので for 文） */
function buildNumberedList(names: string[]): string {
  let log = '';
  for (let i = 0; i < names.length; i++) {
    log += `${i + 1}. ${names[i]}\n`;
  }
  return log;
}

/** 本文 Bad：while で書いた場合も結果は同じ（更新式が埋もれる点が違う） */
function buildNumberedListWithWhile(names: string[]): string {
  let log = '';
  let i = 0;
  while (i < names.length) {
    log += `${i + 1}. ${names[i]}\n`;
    i += 1;
  }
  return log;
}

/** 条件を i <= length にすると存在しない番号まで回る（off-by-one） */
function buildNumberedListOffByOne(names: string[]): string {
  let log = '';
  for (let i = 0; i <= names.length; i++) {
    log += `${i + 1}. ${names[i]}\n`;
  }
  return log;
}

checkString('本文3節: 1から5まで', countUpLog(), '1回目\n2回目\n3回目\n4回目\n5回目\n');
checkString(
  '本文3節: 番号付きリスト',
  buildNumberedList(bodyNames),
  '1. ラベンダーの石けん\n2. ハンドクリーム\n3. マグカップ\n'
);
checkString(
  '本文3節: while 版も同じ出力になる',
  buildNumberedListWithWhile(bodyNames),
  buildNumberedList(bodyNames)
);
checkString(
  '本文3節: i <= length にすると undefined が出る',
  buildNumberedListOffByOne(bodyNames),
  '1. ラベンダーの石けん\n2. ハンドクリーム\n3. マグカップ\n4. undefined\n'
);

// ---------------------------------------------------------------------------
// 本文 4節：for...of（src/session04/for-of.ts）
// ---------------------------------------------------------------------------
const bodyPrices: number[] = [480, 1800, 2350];

/** for...of で合計する（price の型は number になる） */
function sumWithForOf(prices: number[]): number {
  let subtotal = 0;
  for (const price of prices) {
    subtotal += price;
  }
  return subtotal;
}

/** 本文 Bad の型エラーを回避した形（?? で既定値を与える） */
function sumWithIndexAndNullish(prices: number[]): number {
  let subtotal = 0;
  for (let i = 0; i < prices.length; i++) {
    const price = prices[i] ?? 0;
    subtotal += price;
  }
  return subtotal;
}

/** 文字列を1文字ずつ取り出す */
function charsOf(text: string): string {
  let log = '';
  for (const char of text) {
    log += `${char}\n`;
  }
  return log;
}

/** 2つの並びを同じ番号で組み合わせる（番号が要るので for 文） */
function buildPairedList(names: string[], unitPrices: number[]): string {
  let log = '';
  for (let i = 0; i < names.length; i++) {
    const name = names[i] ?? '(不明な商品)';
    const unitPrice = unitPrices[i] ?? 0;
    log += `${name}: ${unitPrice}円\n`;
  }
  return log;
}

checkNumber('本文4節: for...of の合計', sumWithForOf(bodyPrices), 4630);
checkNumber('本文4節: 番号 + ?? でも同じ合計', sumWithIndexAndNullish(bodyPrices), 4630);
checkString('本文4節: 文字列の走査', charsOf('マグカップ'), 'マ\nグ\nカ\nッ\nプ\n');
checkNumber('本文4節: マグカップは5文字', 'マグカップ'.length, 5);
checkString(
  '本文4節: 2つの並びを組み合わせる',
  buildPairedList(['ラベンダーの石けん', 'ハンドクリーム'], [480, 1800]),
  'ラベンダーの石けん: 480円\nハンドクリーム: 1800円\n'
);

// ---------------------------------------------------------------------------
// 本文 5節：break / continue（src/session04/break-continue.ts）
// ---------------------------------------------------------------------------

/** 目的の商品が見つかったら break で打ち切る */
function searchLog(names: string[], target: string): string {
  let found = false;
  let log = '';

  for (const name of names) {
    log += `確認中: ${name}\n`;
    if (name === target) {
      found = true;
      break;
    }
  }

  return `${log}見つかったか: ${found}`;
}

/** continue で在庫切れを飛ばして数える */
function countSellable(stocks: number[]): number {
  let sellableCount = 0;
  for (const stock of stocks) {
    if (stock <= 0) {
      continue;
    }
    sellableCount += 1;
  }
  return sellableCount;
}

/** よくある誤解の確認：continue を break にすると結果が変わる */
function countSellableWithBreak(stocks: number[]): number {
  let sellableCount = 0;
  for (const stock of stocks) {
    if (stock <= 0) {
      break;
    }
    sellableCount += 1;
  }
  return sellableCount;
}

/** 本文 Bad：if の入れ子で単価を合計する */
function sumInStockNested(prices: number[], stocks: number[]): number {
  let total = 0;
  for (let i = 0; i < stocks.length; i++) {
    const stock = stocks[i] ?? 0;
    if (stock > 0) {
      const price = prices[i] ?? 0;
      if (price > 0) {
        total += price;
      }
    }
  }
  return total;
}

/** 本文 Good：continue で対象外を先に切り捨てる */
function sumInStockWithContinue(prices: number[], stocks: number[]): number {
  let total = 0;
  for (let i = 0; i < stocks.length; i++) {
    const stock = stocks[i] ?? 0;
    const price = prices[i] ?? 0;

    if (stock <= 0) {
      continue;
    }
    if (price <= 0) {
      continue;
    }

    total += price;
  }
  return total;
}

const bodyStockPrices: number[] = [480, 1800, 2350, 990];
const bodyStocks: number[] = [0, 12, 3, 0];

checkString(
  '本文5節: break で途中で打ち切る',
  searchLog(bodyNames, 'ハンドクリーム'),
  '確認中: ラベンダーの石けん\n確認中: ハンドクリーム\n見つかったか: true'
);
checkNumber('本文5節: continue で在庫切れを飛ばす', countSellable(bodyStocks), 2);
checkNumber('誤解の確認: break にすると0件になる', countSellableWithBreak(bodyStocks), 0);
checkNumber('参考: 末尾に在庫があれば3件', countSellable([0, 12, 3, 0, 5]), 3);
checkNumber('本文5節 Bad: 入れ子版の合計', sumInStockNested(bodyStockPrices, bodyStocks), 4150);
checkNumber(
  '本文5節 Good: continue 版も同じ合計',
  sumInStockWithContinue(bodyStockPrices, bodyStocks),
  4150
);

// ---------------------------------------------------------------------------
// 本文 6節：多重ループ（src/session04/gift-set.ts）
// ---------------------------------------------------------------------------
const bodyWrappings: string[] = ['クラフト紙', 'リボン付き'];
const bodyCards: string[] = ['ありがとう', 'おめでとう'];

/** 包装紙とカードの全組み合わせ（2 × 2 = 4 通り） */
function buildGiftPairs(wrappings: string[], cards: string[]): string {
  let log = '';
  for (const wrapping of wrappings) {
    for (const card of cards) {
      log += `${wrapping} × ${card}\n`;
    }
  }
  return log;
}

/** よくある誤解の確認：内側で break しても外側は続く（4行 → 2行） */
function buildGiftPairsWithInnerBreak(wrappings: string[], cards: string[]): string {
  let log = '';
  for (const wrapping of wrappings) {
    for (const card of cards) {
      log += `${wrapping} × ${card}\n`;
      break;
    }
  }
  return log;
}

checkString(
  '本文6節: 多重ループの全組み合わせ',
  buildGiftPairs(bodyWrappings, bodyCards),
  'クラフト紙 × ありがとう\n' +
    'クラフト紙 × おめでとう\n' +
    'リボン付き × ありがとう\n' +
    'リボン付き × おめでとう\n'
);
checkString(
  '誤解の確認: 内側の break は外側を抜けない',
  buildGiftPairsWithInnerBreak(bodyWrappings, bodyCards),
  'クラフト紙 × ありがとう\nリボン付き × ありがとう\n'
);

// ---------------------------------------------------------------------------
// 本文 7節：無限ループの回避（src/session04/infinite-loop.ts）
// ---------------------------------------------------------------------------

/** continue を使うループは for で書けば更新式が飛ばされない */
function skipTwoWithFor(): string {
  let log = '';
  for (let i = 0; i < 5; i++) {
    if (i === 2) {
      continue;
    }
    log += `${i}\n`;
  }
  return log;
}

/** 安全弁（MAX_LOOP）で打ち切る。更新を忘れたループを想定 */
function loopWithGuard(): string {
  const MAX_LOOP = 1000;
  let guard = 0;
  let total = 0;

  while (total < FREE_SHIPPING_THRESHOLD) {
    guard += 1;
    if (guard > MAX_LOOP) {
      return `繰り返しが多すぎます（${MAX_LOOP}回で打ち切りました）`;
    }
    // total を更新する行を書き忘れている、という想定
  }

  return `合計 ${total}円`;
}

checkString('本文7節: for + continue は安全', skipTwoWithFor(), '0\n1\n3\n4\n');
checkString(
  '本文7節: 安全弁が働いて止まる',
  loopWithGuard(),
  '繰り返しが多すぎます（1000回で打ち切りました）'
);

// ---------------------------------------------------------------------------
// 本文 8節：カートの合計（src/session04/cart-total.ts）
// ---------------------------------------------------------------------------
function buildCartReport(names: string[], unitPrices: number[], quantities: number[]): string {
  let log = '';
  let subtotal = 0;

  for (let i = 0; i < names.length; i++) {
    const name = names[i] ?? '(不明な商品)';
    const unitPrice = unitPrices[i] ?? 0;
    const quantity = quantities[i] ?? 0;

    const lineTotal = unitPrice * quantity;
    subtotal += lineTotal;

    log += `${name} ${unitPrice}円 × ${quantity}点 = ${lineTotal}円\n`;
  }

  // 支払総額の計算手順（requirements.md の正典。順序を変えない）
  const tax = Math.floor(subtotal * TAX_RATE);
  const totalWithTax = subtotal + tax;
  const shippingFee = totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
  const payableAmount = totalWithTax + shippingFee;

  log += `商品合計（税抜）: ${subtotal}円\n`;
  log += `消費税: ${tax}円\n`;
  log += `商品合計（税込）: ${totalWithTax}円\n`;
  log += `送料: ${shippingFee}円\n`;
  log += `お支払い金額: ${payableAmount}円`;

  return log;
}

checkString(
  '本文8節: カートの明細と支払金額',
  buildCartReport(['ラベンダーの石けん', 'ハンドクリーム'], [480, 1800], [1, 1]),
  'ラベンダーの石けん 480円 × 1点 = 480円\n' +
    'ハンドクリーム 1800円 × 1点 = 1800円\n' +
    '商品合計（税抜）: 2280円\n' +
    '消費税: 228円\n' +
    '商品合計（税込）: 2508円\n' +
    '送料: 500円\n' +
    'お支払い金額: 3008円'
);

// 「送料の判定は税込商品合計」というルールが崩れていないことを確認する
checkNumber('消費税は切り捨てで1回だけ', Math.floor(2280 * TAX_RATE), 228);
checkBoolean('税込2508円は3000円未満', 2508 >= FREE_SHIPPING_THRESHOLD, false);

// ---------------------------------------------------------------------------
// 誤解の確認：for...in は配列に使わない
// ---------------------------------------------------------------------------
function buildForInReport(prices: number[]): string {
  let report = '';
  for (const key in prices) {
    if (report !== '') {
      report += ' ';
    }
    report += `${key}(${typeof key})`;
  }
  return report;
}

/** for...in のキーは文字列なので、+ 1 が連結になる */
function buildForInPlusOne(prices: number[]): string {
  let report = '';
  for (const key in prices) {
    if (report !== '') {
      report += ' ';
    }
    report += key + 1;
  }
  return report;
}

checkString('誤解の確認: for...in のキーは文字列', buildForInReport(bodyPrices), '0(string) 1(string) 2(string)');
checkString('誤解の確認: key + 1 は文字列の連結', buildForInPlusOne(bodyPrices), '01 11 21');

// ---------------------------------------------------------------------------
// 問題1：在庫を出荷しきるまで繰り返す
// ---------------------------------------------------------------------------
const SHIPMENT_UNIT = 2;

function shipInBatches(initialStock: number): string {
  let stock = initialStock;
  let shipmentCount = 0;
  let log = '';

  while (stock > 0) {
    const shipped = stock >= SHIPMENT_UNIT ? SHIPMENT_UNIT : stock;

    stock -= shipped;
    shipmentCount += 1;

    log += `${shipped}個出荷しました。残りの在庫: ${stock}個\n`;
  }

  return `${log}出荷回数: ${shipmentCount}回`;
}

checkString(
  '問題1: 在庫5個',
  shipInBatches(5),
  '2個出荷しました。残りの在庫: 3個\n' +
    '2個出荷しました。残りの在庫: 1個\n' +
    '1個出荷しました。残りの在庫: 0個\n' +
    '出荷回数: 3回'
);
checkString(
  '問題1: 在庫1個',
  shipInBatches(1),
  '1個出荷しました。残りの在庫: 0個\n出荷回数: 1回'
);
checkString('問題1: 在庫0個', shipInBatches(0), '出荷回数: 0回');

// ---------------------------------------------------------------------------
// 問題2：送料無料になる個数を調べる
// ---------------------------------------------------------------------------
function buildFreeShippingTable(): string {
  const SOAP_PRICE = 480;
  const MAX_COUNT = 8;

  let minFreeCount = 0;
  let log = '';

  for (let count = 1; count <= MAX_COUNT; count++) {
    const subtotal = SOAP_PRICE * count;
    const tax = Math.floor(subtotal * TAX_RATE);
    const totalWithTax = subtotal + tax;
    const isFreeShipping = totalWithTax >= FREE_SHIPPING_THRESHOLD;

    if (isFreeShipping && minFreeCount === 0) {
      minFreeCount = count;
    }

    const shippingLabel = isFreeShipping ? '送料無料' : `送料${SHIPPING_FEE}円`;
    log += `${count}個: 税抜 ${subtotal}円 / 税込 ${totalWithTax}円 / ${shippingLabel}\n`;
  }

  return `${log}送料無料になる最小の個数: ${minFreeCount}個`;
}

checkString(
  '問題2: 1個から8個までの表',
  buildFreeShippingTable(),
  '1個: 税抜 480円 / 税込 528円 / 送料500円\n' +
    '2個: 税抜 960円 / 税込 1056円 / 送料500円\n' +
    '3個: 税抜 1440円 / 税込 1584円 / 送料500円\n' +
    '4個: 税抜 1920円 / 税込 2112円 / 送料500円\n' +
    '5個: 税抜 2400円 / 税込 2640円 / 送料500円\n' +
    '6個: 税抜 2880円 / 税込 3168円 / 送料無料\n' +
    '7個: 税抜 3360円 / 税込 3696円 / 送料無料\n' +
    '8個: 税抜 3840円 / 税込 4224円 / 送料無料\n' +
    '送料無料になる最小の個数: 6個'
);

// ---------------------------------------------------------------------------
// 問題3：for...of で並びを集計する
// ---------------------------------------------------------------------------
function sumPrices(prices: number[]): number {
  let total = 0;
  for (const price of prices) {
    total += price;
  }
  return total;
}

function maxPrice(prices: number[]): number {
  let max = 0;
  for (const price of prices) {
    if (price > max) {
      max = price;
    }
  }
  return max;
}

function averagePrice(prices: number[]): number {
  let total = 0;
  let count = 0;

  for (const price of prices) {
    total += price;
    count += 1;
  }

  if (count === 0) {
    return 0;
  }

  return Math.floor(total / count);
}

function spaceOutName(name: string): string {
  let result = '';
  for (const char of name) {
    if (result !== '') {
      result += ' / ';
    }
    result += char;
  }
  return result;
}

const q3Prices: number[] = [480, 1800, 2350, 990];
const q3Empty: number[] = [];

checkNumber('問題3: 合計', sumPrices(q3Prices), 5620);
checkNumber('問題3: 最高値', maxPrice(q3Prices), 2350);
checkNumber('問題3: 平均（切り捨て）', averagePrice(q3Prices), 1405);
checkNumber('問題3: 空の並びの合計', sumPrices(q3Empty), 0);
checkNumber('問題3: 空の並びの最高値', maxPrice(q3Empty), 0);
checkNumber('問題3: 空の並びの平均', averagePrice(q3Empty), 0);
checkString('問題3: マグカップ', spaceOutName('マグカップ'), 'マ / グ / カ / ッ / プ');
checkString('問題3: 石けん', spaceOutName('石けん'), '石 / け / ん');
checkString('問題3: 1文字なら区切りなし', spaceOutName('茶'), '茶');
checkString('問題3: 空文字列', spaceOutName(''), '');

// 問題3の表示4行
checkString(
  '問題3: 出力4行',
  `合計: ${sumPrices(q3Prices)}円\n` +
    `最高値: ${maxPrice(q3Prices)}円\n` +
    `平均: ${averagePrice(q3Prices)}円\n` +
    `${spaceOutName('マグカップ')}`,
  '合計: 5620円\n最高値: 2350円\n平均: 1405円\nマ / グ / カ / ッ / プ'
);

// ---------------------------------------------------------------------------
// 問題4：壊れたループを直す
// ---------------------------------------------------------------------------
const MAX_LOOP = 100;

/** (A) 更新式を足し、安全弁も入れた版 */
function countDownStock(initialStock: number): string {
  let stock = initialStock;
  let guard = 0;
  let log = '';

  while (stock > 0) {
    guard += 1;
    if (guard > MAX_LOOP) {
      return `${log}繰り返しが多すぎます。条件を見直してください`;
    }

    log += `残り ${stock}個\n`;
    stock -= 1;
  }

  return `${log}在庫がなくなりました`;
}

checkString(
  '問題4(A): 在庫5個から数え下げる',
  countDownStock(5),
  '残り 5個\n残り 4個\n残り 3個\n残り 2個\n残り 1個\n在庫がなくなりました'
);
// 安全弁の動作確認：在庫が MAX_LOOP を超えると打ち切りメッセージで終わる
const q4Guarded = countDownStock(200);
checkBoolean(
  '問題4(A): 安全弁のメッセージで終わる',
  q4Guarded.endsWith('繰り返しが多すぎます。条件を見直してください'),
  true
);
checkNumber('問題4(A): 安全弁は100回で打ち切る', q4Guarded.split('\n').length, MAX_LOOP + 1);
checkString('問題4(B): 2だけ飛ばす', skipTwoWithFor(), '0\n1\n3\n4\n');
checkNumber('問題4(C): for...of で正しく合計できる', sumPrices(bodyPrices), 4630);
checkString(
  '問題4(C): for...in の確認行',
  buildForInReport(bodyPrices),
  '0(string) 1(string) 2(string)'
);

// ---------------------------------------------------------------------------
// 問題5：break と continue で在庫を調べる
// ---------------------------------------------------------------------------
const q5Names: string[] = [
  'ラベンダーの石けん',
  'ハンドクリーム',
  'マグカップ',
  'リネンのふきん',
];
const q5UnitPrices: number[] = [480, 1800, 2350, 990];
const q5Stocks: number[] = [0, 12, 3, 0];

function findFirstInStockIndex(stockList: number[]): number {
  let foundIndex = -1;

  for (let i = 0; i < stockList.length; i++) {
    const stock = stockList[i] ?? 0;
    if (stock > 0) {
      foundIndex = i;
      break;
    }
  }

  return foundIndex;
}

/** 別解：早期 return 版（解答章の別解） */
function findFirstInStockIndexByReturn(stockList: number[]): number {
  for (let i = 0; i < stockList.length; i++) {
    const stock = stockList[i] ?? 0;
    if (stock > 0) {
      return i;
    }
  }
  return -1;
}

function countInStock(stockList: number[]): number {
  let count = 0;
  for (const stock of stockList) {
    if (stock <= 0) {
      continue;
    }
    count += 1;
  }
  return count;
}

function sumInStockPrices(priceList: number[], stockList: number[]): number {
  let total = 0;

  for (let i = 0; i < stockList.length; i++) {
    const stock = stockList[i] ?? 0;
    const unitPrice = priceList[i] ?? 0;

    if (stock <= 0) {
      continue;
    }

    total += unitPrice;
  }

  return total;
}

function listInStockNames(nameList: string[], stockList: number[]): string {
  let result = '';

  for (let i = 0; i < stockList.length; i++) {
    const stock = stockList[i] ?? 0;
    const name = nameList[i] ?? '(不明な商品)';

    if (stock <= 0) {
      continue;
    }

    if (result !== '') {
      result += ' / ';
    }
    result += name;
  }

  if (result === '') {
    return '(在庫のある商品はありません)';
  }

  return result;
}

checkNumber('問題5: 最初に在庫がある番号', findFirstInStockIndex(q5Stocks), 1);
checkNumber('問題5: 見つからなければ -1', findFirstInStockIndex([0, 0]), -1);
checkNumber('問題5: 別解も同じ結果', findFirstInStockIndexByReturn(q5Stocks), 1);
checkNumber('問題5: 別解も -1 を返す', findFirstInStockIndexByReturn([0, 0]), -1);
checkNumber('問題5: 在庫がある件数', countInStock(q5Stocks), 2);
checkNumber('問題5: 全部在庫切れなら0件', countInStock([0, 0, 0, 0]), 0);
checkNumber('問題5: 在庫がある商品の単価合計', sumInStockPrices(q5UnitPrices, q5Stocks), 4150);
checkString(
  '問題5: 在庫がある商品名',
  listInStockNames(q5Names, q5Stocks),
  'ハンドクリーム / マグカップ'
);
checkString(
  '問題5: 1件もなければ案内を返す',
  listInStockNames(q5Names, [0, 0, 0, 0]),
  '(在庫のある商品はありません)'
);
checkString(
  '問題5: 出力4行',
  `最初に在庫がある番号: ${findFirstInStockIndex(q5Stocks)}\n` +
    `在庫がある商品: ${countInStock(q5Stocks)}件\n` +
    `在庫がある商品の単価合計: ${sumInStockPrices(q5UnitPrices, q5Stocks)}円\n` +
    `在庫がある商品: ${listInStockNames(q5Names, q5Stocks)}`,
  '最初に在庫がある番号: 1\n' +
    '在庫がある商品: 2件\n' +
    '在庫がある商品の単価合計: 4150円\n' +
    '在庫がある商品: ハンドクリーム / マグカップ'
);

// ---------------------------------------------------------------------------
// 問題6：多重ループでギフトセットを組み合わせる
// ---------------------------------------------------------------------------
function buildGiftCombinations(names: string[], unitPrices: number[]): string {
  let combinationCount = 0;
  let freeShippingCount = 0;
  let log = '';

  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      const firstName = names[i] ?? '(不明な商品)';
      const secondName = names[j] ?? '(不明な商品)';
      const subtotal = (unitPrices[i] ?? 0) + (unitPrices[j] ?? 0);

      const tax = Math.floor(subtotal * TAX_RATE);
      const totalWithTax = subtotal + tax;
      const shippingFee = totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
      const payableAmount = totalWithTax + shippingFee;

      combinationCount += 1;
      if (shippingFee === 0) {
        freeShippingCount += 1;
      }

      log +=
        `${firstName} + ${secondName}: 税抜 ${subtotal}円 / 税込 ${totalWithTax}円 / ` +
        `送料 ${shippingFee}円 / お支払い ${payableAmount}円\n`;
    }
  }

  log += `組み合わせ数: ${combinationCount}通り\n`;
  log += `送料無料になる組み合わせ: ${freeShippingCount}通り`;

  return log;
}

const q6Names: string[] = ['ラベンダーの石けん', 'ハンドクリーム', 'マグカップ'];
const q6UnitPrices: number[] = [480, 1800, 2350];

checkString(
  '問題6: 3種類から2つ選ぶ全組み合わせ',
  buildGiftCombinations(q6Names, q6UnitPrices),
  'ラベンダーの石けん + ハンドクリーム: 税抜 2280円 / 税込 2508円 / 送料 500円 / お支払い 3008円\n' +
    'ラベンダーの石けん + マグカップ: 税抜 2830円 / 税込 3113円 / 送料 0円 / お支払い 3113円\n' +
    'ハンドクリーム + マグカップ: 税抜 4150円 / 税込 4565円 / 送料 0円 / お支払い 4565円\n' +
    '組み合わせ数: 3通り\n' +
    '送料無料になる組み合わせ: 2通り'
);
checkNumber('問題6: 2830円の消費税', Math.floor(2830 * TAX_RATE), 283);
checkNumber('問題6: 4150円の消費税', Math.floor(4150 * TAX_RATE), 415);

// ---------------------------------------------------------------------------
// 問題7：カートの明細を組み立てる
// ---------------------------------------------------------------------------
const AMOUNT_WIDTH = 6;
const SEPARATOR_LENGTH = 24;

function formatAmount(amount: number): string {
  return String(amount).padStart(AMOUNT_WIDTH, ' ');
}

function buildSeparator(length: number): string {
  let line = '';
  for (let i = 0; i < length; i++) {
    line += '-';
  }
  return line;
}

function buildCartReceipt(
  names: string[],
  unitPrices: number[],
  quantities: number[],
  stocks: number[]
): string {
  let log = '=== ご注文明細 ===\n';
  let subtotal = 0;
  let orderedLineCount = 0;

  for (let i = 0; i < names.length; i++) {
    const name = names[i] ?? '(不明な商品)';
    const unitPrice = unitPrices[i] ?? 0;
    const quantity = quantities[i] ?? 0;
    const stock = stocks[i] ?? 0;

    if (quantity <= 0) {
      continue;
    }

    if (stock <= 0) {
      log += `${name}: 在庫切れのため注文できません\n`;
      continue;
    }

    const lineTotal = unitPrice * quantity;
    subtotal += lineTotal;
    orderedLineCount += 1;

    log += `${name} × ${quantity}点: ${formatAmount(lineTotal)}円\n`;
  }

  if (orderedLineCount === 0) {
    return `${log}カートに購入できる商品がありません`;
  }

  const tax = Math.floor(subtotal * TAX_RATE);
  const totalWithTax = subtotal + tax;
  const shippingFee = totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
  const payableAmount = totalWithTax + shippingFee;

  log += `${buildSeparator(SEPARATOR_LENGTH)}\n`;
  log += `商品合計（税抜）: ${formatAmount(subtotal)}円\n`;
  log += `消費税: ${formatAmount(tax)}円\n`;
  log += `商品合計（税込）: ${formatAmount(totalWithTax)}円\n`;
  log += `送料: ${formatAmount(shippingFee)}円\n`;
  log += `お支払い金額: ${formatAmount(payableAmount)}円`;

  return log;
}

const q7Names: string[] = [
  'ラベンダーの石けん',
  'ハンドクリーム',
  'マグカップ',
  'リネンのふきん',
];
const q7UnitPrices: number[] = [480, 1800, 2350, 990];
const q7Quantities: number[] = [2, 1, 0, 3];
const q7Stocks: number[] = [10, 0, 5, 8];

// 桁そろえの結果（padStart の埋め方を明示的に検証する）
checkString('問題7: 960 の桁そろえ', formatAmount(960), '   960');
checkString('問題7: 2970 の桁そろえ', formatAmount(2970), '  2970');
checkString('問題7: 393 の桁そろえ', formatAmount(393), '   393');
checkString('問題7: 0 の桁そろえ', formatAmount(0), '     0');
checkNumber('問題7: 区切り線は24文字', buildSeparator(SEPARATOR_LENGTH).length, 24);
checkString(
  '問題7: 区切り線の中身',
  buildSeparator(SEPARATOR_LENGTH),
  '--------' + '--------' + '--------'
);

checkString(
  '問題7: 明細の全文',
  buildCartReceipt(q7Names, q7UnitPrices, q7Quantities, q7Stocks),
  '=== ご注文明細 ===\n' +
    'ラベンダーの石けん × 2点: ' +
    '   960' +
    '円\n' +
    'ハンドクリーム: 在庫切れのため注文できません\n' +
    'リネンのふきん × 3点: ' +
    '  2970' +
    '円\n' +
    '--------' +
    '--------' +
    '--------' +
    '\n' +
    '商品合計（税抜）: ' +
    '  3930' +
    '円\n' +
    '消費税: ' +
    '   393' +
    '円\n' +
    '商品合計（税込）: ' +
    '  4323' +
    '円\n' +
    '送料: ' +
    '     0' +
    '円\n' +
    'お支払い金額: ' +
    '  4323' +
    '円'
);
checkString(
  '問題7: 購入できる商品が無い場合',
  buildCartReceipt(q7Names, q7UnitPrices, [0, 0, 0, 0], q7Stocks),
  '=== ご注文明細 ===\nカートに購入できる商品がありません'
);

// 金額の検算（本文・解答章に書いた数値）
checkNumber('問題7: 税抜合計', 480 * 2 + 990 * 3, 3930);
checkNumber('問題7: 消費税', Math.floor(3930 * TAX_RATE), 393);
checkNumber('問題7: 税込商品合計', 3930 + 393, 4323);
checkBoolean('問題7: 税込4323円は送料無料', 4323 >= FREE_SHIPPING_THRESHOLD, true);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session04: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session04: ok');
