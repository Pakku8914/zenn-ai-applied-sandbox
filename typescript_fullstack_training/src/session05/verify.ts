/**
 * セッション5「関数」の検証スクリプト。
 *
 * 本文（014）と練習問題の解答（016）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * 実行: docker compose exec ts npx tsx src/session05/verify.ts
 */

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

/**
 * 表示専用の関数（void）の出力を検証するため、console.log を一時的に差し替えて
 * 出力行を集める。章の「期待される出力」と1行ずつ突き合わせるために使う。
 */
function captureLogs(run: () => void): string[] {
  const lines: string[] = [];
  const original: typeof console.log = console.log;
  // console.log と同じ型で受けることで、差し替えの型が確実に一致する
  const collect: typeof console.log = (...args) => {
    lines.push(args.map((value: unknown) => String(value)).join(' '));
  };
  console.log = collect;
  try {
    run();
  } finally {
    console.log = original;
  }
  return lines;
}

/** 集めた出力行を1つの文字列にして比較する（行数の違いも検出できる） */
function checkLines(label: string, actual: string[], expected: string[]): void {
  checkString(label, actual.join('\n'), expected.join('\n'));
}

// ---------------------------------------------------------------------------
// 共通の定数（本書は金額を整数の円で扱う）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1; // 消費税率10%
const SHIPPING_FEE = 500; // 送料（円）
const FREE_SHIPPING_THRESHOLD = 3000; // 税込商品合計がこの額以上で送料無料

// ---------------------------------------------------------------------------
// 本文 4節：巻き上げ（関数宣言は定義より前から呼べる）
//   ここで calcTaxDeclared を「定義より前の行」から呼んでいる。
// ---------------------------------------------------------------------------
checkNumber('巻き上げ: 関数宣言は定義より前から呼べる', calcTaxDeclared(2622), 262);

function calcTaxDeclared(amount: number): number {
  return Math.floor(amount * TAX_RATE);
}

// ---------------------------------------------------------------------------
// 本文 1節・問題1：関数の定義と呼び出し
// ---------------------------------------------------------------------------

/** 明細1行の金額を求める（単価 × 数量） */
function calcLineTotal(unitPrice: number, quantity: number): number {
  return unitPrice * quantity;
}

/** 問題1：表示用の明細行を組み立てる */
function buildLineText(name: string, unitPrice: number, quantity: number): string {
  const lineTotal = calcLineTotal(unitPrice, quantity);
  return `${name} ${unitPrice}円 × ${quantity}点 = ${lineTotal}円`;
}

checkNumber('本文: calcLineTotal(1800, 1)', calcLineTotal(1800, 1), 1800);
checkNumber('本文: calcLineTotal(480, 2)', calcLineTotal(480, 2), 960);
checkNumber('本文: calcLineTotal(2350, 3)', calcLineTotal(2350, 3), 7050);

// 本文1節 Bad：型注釈がないと文字列が勝手に数値化されるか NaN になる
// （TypeScript では 'x' * 2 と直接書けないため、Number() で同じ変換を再現する）
checkNumber("本文1節 Bad: '1800' * 2 は 3600 になる", Number('1800') * 2, 3600);
checkBoolean("本文1節 Bad: '2点' が混ざると NaN", Number.isNaN(1800 * Number('2点')), true);

// 仮引数の名前と実引数の変数名が違っても動く（本文「よくある誤解」）
const price = 480;
const count = 2;
checkNumber('本文: 別名の変数を渡しても同じ結果', calcLineTotal(price, count), 960);

checkLines(
  '問題1: 明細3行の出力',
  captureLogs(() => {
    console.log(buildLineText('ハンドクリーム', 1800, 1));
    console.log(buildLineText('ラベンダーの石けん', 480, 2));
    console.log(buildLineText('マグカップ', 2350, 3));
  }),
  [
    'ハンドクリーム 1800円 × 1点 = 1800円',
    'ラベンダーの石けん 480円 × 2点 = 960円',
    'マグカップ 2350円 × 3点 = 7050円',
  ]
);

// ---------------------------------------------------------------------------
// 本文 2節・問題2：戻り値のない関数（void）
// ---------------------------------------------------------------------------

/** 金額の行を表示する（値は返さない） */
function printAmountLine(label: string, amount: number): void {
  console.log(`${label}: ${amount}円`);
}

/** 区切り線を表示する。引数も戻り値もない */
function printSeparator(): void {
  console.log('-'.repeat(12));
}

/** 在庫が少ないときだけ警告を表示する */
function printLowStockWarning(stock: number): void {
  // ガード節：在庫が十分なら何も表示せずに抜ける
  if (stock > 5) {
    return;
  }
  console.log(`在庫がわずかです（残り${stock}点）`);
}

// 章に載せた区切り線はハイフン12個（数え間違いを防ぐため repeat で表す）
const separatorLine = '---'.repeat(4);
checkNumber('本文: 区切り線は12文字', separatorLine.length, 12);
checkString('本文: 区切り線は repeat(12) と一致', '-'.repeat(12), separatorLine);

checkLines(
  '本文2節: 表示関数の出力',
  captureLogs(() => {
    printAmountLine('小計', 2760);
    printSeparator();
    printAmountLine('お支払金額', 3036);
  }),
  ['小計: 2760円', separatorLine, 'お支払金額: 3036円']
);

checkNumber(
  '本文2節: 在庫12点では何も表示しない',
  captureLogs(() => {
    printLowStockWarning(12);
  }).length,
  0
);

checkLines(
  '問題2: 表示は3行になる',
  captureLogs(() => {
    printAmountLine('小計', 2760);
    printSeparator();
    printLowStockWarning(12);
    printLowStockWarning(3);
  }),
  ['小計: 2760円', separatorLine, '在庫がわずかです（残り3点）']
);

checkLines(
  '問題2: 境界（在庫5点）は警告が出る',
  captureLogs(() => {
    printLowStockWarning(5);
    printLowStockWarning(6);
  }),
  ['在庫がわずかです（残り5点）']
);

// ---------------------------------------------------------------------------
// 本文 3節・問題3：デフォルト引数とオプショナル引数
// ---------------------------------------------------------------------------

/** 消費税額を求める。税率は既定で TAX_RATE */
function calcTax(amount: number, taxRate: number = TAX_RATE): number {
  return Math.floor(amount * taxRate);
}

/** 商品名にバッジを付けた表示名を作る。バッジは無いこともある */
function formatProductLabel(name: string, badge?: string): string {
  if (badge === undefined) {
    return name;
  }
  return `${name}【${badge}】`;
}

/** ?? で既定値を入れる版（本文3節） */
function formatProductLabelWithFallback(name: string, badge?: string): string {
  const badgeText = badge ?? 'なし';
  return `${name}【${badgeText}】`;
}

checkNumber('本文: calcTax(2622) はデフォルト引数の10%', calcTax(2622), 262);
checkNumber('本文: calcTax(2622, 0.08)', calcTax(2622, 0.08), 209);
checkNumber('本文: calcTax(2760) の10%', calcTax(2760), 276);
checkString('本文: バッジなし', formatProductLabel('マグカップ'), 'マグカップ');
checkString(
  '本文: バッジあり',
  formatProductLabel('マグカップ', '残りわずか'),
  'マグカップ【残りわずか】'
);
checkString('本文: ?? で既定値', formatProductLabelWithFallback('マグカップ'), 'マグカップ【なし】');
// 引数の順番を入れ替えると意味が変わる（本文「よくある誤解」の確認方法）
checkString(
  '本文: 引数を入れ替えると表示が入れ替わる',
  formatProductLabel('新着', 'マグカップ'),
  '新着【マグカップ】'
);

// オプショナル引数を省略すると undefined（空文字列や 0 にはならない）
function describeOptional(value?: string): string {
  return String(value);
}
checkString('本文: 省略した引数は undefined', describeOptional(), 'undefined');

checkLines(
  '問題3: 4行の出力',
  captureLogs(() => {
    console.log(calcTax(2622));
    console.log(calcTax(2622, 0.08));
    console.log(formatProductLabel('マグカップ'));
    console.log(formatProductLabel('マグカップ', '残りわずか'));
  }),
  ['262', '209', 'マグカップ', 'マグカップ【残りわずか】']
);

// ---------------------------------------------------------------------------
// 本文 4節：アロー関数の一時的デッドゾーン（初期化前に呼ぶと ReferenceError）
//   直接 lateArrow を呼ぶと型エラー（TS2448）になるため、関数の中から呼ぶ形で
//   実行時の挙動だけを確認する。
// ---------------------------------------------------------------------------
function callLateArrowEarly(): number {
  return lateArrow(480, 2);
}

let tdzErrorName = '';
try {
  callLateArrowEarly();
} catch (error) {
  tdzErrorName = error instanceof Error ? error.name : 'unknown';
}

const lateArrow = (unitPrice: number, quantity: number): number => unitPrice * quantity;

checkString('本文4節: 初期化前のアロー関数は ReferenceError', tdzErrorName, 'ReferenceError');
checkNumber('本文4節: 初期化後は普通に呼べる', lateArrow(480, 2), 960);
checkNumber('本文4節: アロー関数の短縮形も同じ結果', callLateArrowEarly(), 960);

/** 本文4節 Bad/Good：定義してから使う */
function buildSummary(subtotal: number): string {
  return `小計は${subtotal}円です`;
}
checkString('本文4節: buildSummary(2760)', buildSummary(2760), '小計は2760円です');

// ---------------------------------------------------------------------------
// 本文 5節：スコープと変数の寿命
// ---------------------------------------------------------------------------
function calcTaxWithLog(amount: number): number {
  const tax = Math.floor(amount * TAX_RATE); // 関数スコープ

  if (tax > 200) {
    const note = '税額が200円を超えています'; // ブロックスコープ
    console.log(note);
  }

  return tax;
}

checkLines(
  '本文5節: 2622円のときは注記が出る',
  captureLogs(() => {
    console.log(calcTaxWithLog(2622));
  }),
  ['税額が200円を超えています', '262']
);
checkLines(
  '本文5節: 1000円のときは注記が出ない',
  captureLogs(() => {
    console.log(calcTaxWithLog(1000));
  }),
  ['100']
);

/** 関数の中の変数は呼び出しごとに作り直される（寿命） */
function countUpLocal(): number {
  let count = 0;
  count += 1;
  return count;
}
checkNumber('本文5節: 1回目の countUpLocal', countUpLocal(), 1);
checkNumber('本文5節: 2回目も 1 のまま', countUpLocal(), 1);

// ---------------------------------------------------------------------------
// 本文 6節・問題5：純粋関数と副作用
// ---------------------------------------------------------------------------

// Bad：関数の外の変数を書き換える（同じ呼び出しでも結果が変わる）
let impureTotalQuantity = 0;

function addQuantity(quantity: number): void {
  impureTotalQuantity += quantity;
}

addQuantity(1);
addQuantity(2);
checkNumber('本文6節 Bad: 1回目の合計', impureTotalQuantity, 3);
addQuantity(1);
addQuantity(2);
checkNumber('本文6節 Bad: 同じ呼び出しで結果が変わる', impureTotalQuantity, 6);

/** Good：数量の一覧から合計点数を求める純粋関数 */
function calcTotalQuantity(quantities: number[]): number {
  let totalQuantity = 0;
  for (const quantity of quantities) {
    totalQuantity += quantity;
  }
  return totalQuantity;
}

const bodyQuantities: number[] = [1, 2];
checkNumber('本文6節 Good: 1回目', calcTotalQuantity(bodyQuantities), 3);
checkNumber('本文6節 Good: 2回目も同じ', calcTotalQuantity(bodyQuantities), 3);

/** 明細金額の一覧から小計（税抜）を求める */
function calcSubtotal(lineTotals: number[]): number {
  let subtotal = 0;
  for (const lineTotal of lineTotals) {
    subtotal += lineTotal;
  }
  return subtotal;
}

checkNumber('本文: calcSubtotal([1800, 960])', calcSubtotal([1800, 960]), 2760);
checkNumber('本文: 空の一覧の小計は 0', calcSubtotal([]), 0);

// 問題5：副作用ありの集計と、純粋関数版の集計が同じ答えになること
let q5Quantity = 0;
let q5Subtotal = 0;
function q5AddLine(unitPrice: number, quantity: number): void {
  q5Quantity += quantity;
  q5Subtotal += unitPrice * quantity;
}
q5AddLine(1800, 1);
q5AddLine(480, 2);
q5AddLine(2350, 1);
checkString('問題5: 元のコードの出力', `${q5Quantity}点 / 小計${q5Subtotal}円`, '4点 / 小計5110円');

// 1行増やすと出力が変わる（本文で説明している副作用の怖さ）
q5AddLine(480, 2);
checkString(
  '問題5: 呼び出しを1行増やすと結果が変わる',
  `${q5Quantity}点 / 小計${q5Subtotal}円`,
  '6点 / 小計6070円'
);

const q5LineTotals: number[] = [
  calcLineTotal(1800, 1),
  calcLineTotal(480, 2),
  calcLineTotal(2350, 1),
];
const q5Quantities: number[] = [1, 2, 1];

checkLines(
  '問題5: 純粋関数版の出力',
  captureLogs(() => {
    console.log(`${calcTotalQuantity(q5Quantities)}点 / 小計${calcSubtotal(q5LineTotals)}円`);
    console.log(
      `2回呼んでも同じ結果: ${calcSubtotal(q5LineTotals) === calcSubtotal(q5LineTotals)}`
    );
  }),
  ['4点 / 小計5110円', '2回呼んでも同じ結果: true']
);

// ---------------------------------------------------------------------------
// 本文 7節・問題6：支払総額を関数に分解する
// ---------------------------------------------------------------------------

/** 小計と割引率（%）から割引額を求める。1円未満は切り捨て */
function calcDiscountAmount(subtotal: number, discountPercent: number): number {
  return Math.floor((subtotal * discountPercent) / 100);
}

/** 送料を求める。判定の基準は「税込商品合計」 */
function calcShippingFee(totalWithTax: number): number {
  if (totalWithTax >= FREE_SHIPPING_THRESHOLD) {
    return 0;
  }
  return SHIPPING_FEE;
}

/** 累計購入額から会員ランクを求める（セッション3で作成） */
function resolveMemberRank(totalSpent: number): string {
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

/** 会員ランクに応じた割引率（%）（セッション3で作成） */
function discountPercentByRank(rank: string): number {
  switch (rank) {
    case 'gold':
      return 10;
    case 'silver':
      return 5;
    case 'bronze':
      return 3;
    default:
      return 0;
  }
}

/** 支払総額（税込商品合計 + 送料）。totalSpent の既定は 0（割引なし） */
function calcPayableAmount(subtotal: number, totalSpent: number = 0): number {
  // ガード節：カートが空なら支払いは発生しない
  if (subtotal <= 0) {
    return 0;
  }

  const discountPercent = discountPercentByRank(resolveMemberRank(totalSpent));
  const discountAmount = calcDiscountAmount(subtotal, discountPercent);
  const discountedTotal = subtotal - discountAmount;
  const tax = calcTax(discountedTotal);
  const totalWithTax = discountedTotal + tax;
  return totalWithTax + calcShippingFee(totalWithTax);
}

// 送料の判定は税込商品合計で行う（本書の正典）
checkNumber('本文: 送料 3000円ちょうどは無料', calcShippingFee(3000), 0);
checkNumber('本文: 送料 2999円は500円', calcShippingFee(2999), SHIPPING_FEE);
checkNumber('本文: 送料 3036円は無料', calcShippingFee(3036), 0);
checkNumber('本文: 送料 2884円は500円', calcShippingFee(2884), SHIPPING_FEE);

// 割引率
checkNumber('本文: silver の割引額（2760円の5%）', calcDiscountAmount(2760, 5), 138);
checkNumber('本文: gold の割引額（2760円の10%）', calcDiscountAmount(2760, 10), 276);
checkNumber('本文: 割引なし', calcDiscountAmount(2760, 0), 0);
checkNumber('本文: bronze の割引額（3000円の3%）', calcDiscountAmount(3000, 3), 90);

// ランクと割引率（セッション3から変えていないこと）
checkString('本文: 累計25000円は silver', resolveMemberRank(25000), 'silver');
checkString('本文: 累計60000円は gold', resolveMemberRank(60000), 'gold');
checkString('本文: 累計6000円は bronze', resolveMemberRank(6000), 'bronze');
checkString('本文: 累計0円は none', resolveMemberRank(0), 'none');
checkNumber('本文: silver の割引率', discountPercentByRank('silver'), 5);
checkNumber('本文: 未知のランクは0%', discountPercentByRank('platinum'), 0);

// 本文7節の実行結果
const bodySubtotal = calcSubtotal([calcLineTotal(1800, 1), calcLineTotal(480, 2)]);
checkNumber('本文7節: 小計', bodySubtotal, 2760);
checkLines(
  '本文7節: payable.ts の出力',
  captureLogs(() => {
    console.log(bodySubtotal);
    console.log(calcPayableAmount(bodySubtotal));
    console.log(calcPayableAmount(bodySubtotal, 25000));
    console.log(calcPayableAmount(bodySubtotal, 60000));
  }),
  ['2760', '3036', '3384', '3232']
);

// 本文7節の表（中間の値）
checkNumber('本文7節 表: none の税込商品合計', 2760 + calcTax(2760), 3036);
checkNumber('本文7節 表: silver の税込商品合計', 2622 + calcTax(2622), 2884);
checkNumber('本文7節 表: gold の税込商品合計', 2484 + calcTax(2484), 2732);
checkNumber('本文7節 表: silver の消費税', calcTax(2622), 262);
checkNumber('本文7節 表: gold の消費税', calcTax(2484), 248);
checkBoolean(
  '本文7節: 割引ありのほうが支払総額が高い',
  calcPayableAmount(2760, 25000) > calcPayableAmount(2760),
  true
);

// 問題6の入出力仕様
checkLines(
  '問題6: 6行の出力',
  captureLogs(() => {
    console.log(calcPayableAmount(2760));
    console.log(calcPayableAmount(2760, 25000));
    console.log(calcPayableAmount(2760, 60000));
    console.log(calcPayableAmount(5000));
    console.log(calcPayableAmount(3000, 6000));
    console.log(calcPayableAmount(0, 60000));
  }),
  ['3036', '3384', '3232', '5500', '3201', '0']
);

// 別解（三項演算子版）が同じ結果になること
function calcShippingFeeByTernary(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}
checkNumber('問題6 別解: 2884円', calcShippingFeeByTernary(2884), calcShippingFee(2884));
checkNumber('問題6 別解: 3036円', calcShippingFeeByTernary(3036), calcShippingFee(3036));

// ---------------------------------------------------------------------------
// 問題7：レシートを組み立てる
// ---------------------------------------------------------------------------

/** 金額を指定の幅で右そろえした文字列にする */
function padAmount(amount: number, width: number): string {
  return String(amount).padStart(width, ' ');
}

/** 送料無料まであといくら必要か（すでに無料なら 0） */
function calcRemainingForFreeShipping(totalWithTax: number): number {
  return Math.max(0, FREE_SHIPPING_THRESHOLD - totalWithTax);
}

/** レシート全文を組み立てて返す。表示は一切しない（純粋関数） */
function buildReceiptText(subtotal: number, totalSpent: number = 0, width: number = 6): string {
  const discountPercent = discountPercentByRank(resolveMemberRank(totalSpent));
  const discountAmount = calcDiscountAmount(subtotal, discountPercent);
  const discountedTotal = subtotal - discountAmount;
  const tax = calcTax(discountedTotal);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);
  const payableAmount = calcPayableAmount(subtotal, totalSpent);

  // 送料が発生したときだけ「あといくらで無料か」を案内する
  const lastLine =
    shippingFee > 0
      ? `送料無料まであと: ${padAmount(calcRemainingForFreeShipping(totalWithTax), width)}円`
      : '送料無料が適用されました';

  return `=== ご注文明細 ===
小計: ${padAmount(subtotal, width)}円
割引: ${padAmount(discountAmount, width)}円
消費税: ${padAmount(tax, width)}円
送料: ${padAmount(shippingFee, width)}円
お支払金額: ${padAmount(payableAmount, width)}円
${lastLine}`;
}

/** 組み立てた文字列を表示するだけ。計算はしない */
function printReceipt(subtotal: number, totalSpent: number = 0): void {
  console.log(buildReceiptText(subtotal, totalSpent));
}

checkString('問題7: padAmount(138, 6)', padAmount(138, 6), `${' '.repeat(3)}138`);
checkString('問題7: padAmount(2760, 6)', padAmount(2760, 6), `${' '.repeat(2)}2760`);
checkString('問題7: padAmount(0, 6)', padAmount(0, 6), `${' '.repeat(5)}0`);
checkNumber('問題7: 2884円は送料無料まであと116円', calcRemainingForFreeShipping(2884), 116);
checkNumber('問題7: 3036円はすでに無料なので0', calcRemainingForFreeShipping(3036), 0);

// 章に載せた出力例と1文字ずつ突き合わせる。空白の数を数え間違えないよう、
// 「ラベルの直後の1つ + padStart による右そろえ分」を repeat で明示する。
const q7ReceiptSilver = [
  '=== ご注文明細 ===',
  `小計:${' '.repeat(1 + 2)}2760円`,
  `割引:${' '.repeat(1 + 3)}138円`,
  `消費税:${' '.repeat(1 + 3)}262円`,
  `送料:${' '.repeat(1 + 3)}500円`,
  `お支払金額:${' '.repeat(1 + 2)}3384円`,
  `送料無料まであと:${' '.repeat(1 + 3)}116円`,
].join('\n');

const q7ReceiptNone = [
  '=== ご注文明細 ===',
  `小計:${' '.repeat(1 + 2)}2760円`,
  `割引:${' '.repeat(1 + 5)}0円`,
  `消費税:${' '.repeat(1 + 3)}276円`,
  `送料:${' '.repeat(1 + 5)}0円`,
  `お支払金額:${' '.repeat(1 + 2)}3036円`,
  '送料無料が適用されました',
].join('\n');

checkString('問題7: silver のレシート', buildReceiptText(2760, 25000), q7ReceiptSilver);
checkString('問題7: 割引なしのレシート', buildReceiptText(2760), q7ReceiptNone);
checkNumber('問題7: レシートは7行', buildReceiptText(2760, 25000).split('\n').length, 7);

checkLines(
  '問題7: printReceipt を2回呼んだ出力',
  captureLogs(() => {
    printReceipt(2760, 25000);
    printReceipt(2760);
  }),
  [q7ReceiptSilver, q7ReceiptNone]
);

// 幅を変えても中身は変わらない（デフォルト引数の差し替え）
checkString(
  '問題7: 幅8を指定した小計の行',
  buildReceiptText(2760, 25000, 8).split('\n')[1] ?? '',
  `小計:${' '.repeat(1 + 4)}2760円`
);

// buildReceiptText は純粋関数なので、何度呼んでも同じ文字列になる
checkBoolean(
  '問題7: 2回呼んでも同じ結果（純粋関数）',
  buildReceiptText(2760, 25000) === buildReceiptText(2760, 25000),
  true
);

// ---------------------------------------------------------------------------
// 問題4：スコープと巻き上げ（修正後のコード）
// ---------------------------------------------------------------------------
const calcShippingFeeArrow = (totalWithTax: number): number => {
  if (totalWithTax >= FREE_SHIPPING_THRESHOLD) {
    return 0;
  }
  return SHIPPING_FEE;
};

function describeCart(subtotal: number): string {
  if (subtotal <= 0) {
    return 'カートは空です';
  }
  return `小計は${subtotal}円です`;
}

checkLines(
  '問題4: 修正後の4行の出力',
  captureLogs(() => {
    console.log(calcShippingFeeArrow(3036));
    console.log(calcShippingFeeArrow(2884));
    console.log(describeCart(2760));
    console.log(describeCart(0));
  }),
  ['0', '500', '小計は2760円です', 'カートは空です']
);

// 引数はコピーされるので、呼び出し元の変数は変わらない（本文「よくある誤解」）
function addOne(value: number): void {
  value += 1;
}
let originalNumber = 5; // 本文の例と同じく let で宣言する
addOne(originalNumber);
checkNumber('本文: プリミティブは値のコピーが渡される', originalNumber, 5);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session05: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session05: ok');
