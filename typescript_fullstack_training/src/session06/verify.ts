/**
 * セッション6「関数の応用」のコード例と練習問題の解答を検証する。
 * 期待値と一致しなければエラー終了する。
 */

/** 比較できる値（== の暗黙変換を避けるため、比較は常に !== で行う） */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}: 期待値 ${String(expected)} / 実際 ${String(actual)}`);
    process.exit(1);
  }
};

// 本書の共通ルール（requirements.md の共通シナリオで固定）
const TAX_RATE = 0.1; // 消費税率10%
const SHIPPING_FEE = 500; // 送料（円）
const FREE_SHIPPING_THRESHOLD = 3000; // 税込商品合計がこの金額以上で送料無料（円）

// ---------------------------------------------------------------------------
// 1. 関数は値である（本文「1. 関数は値である（第一級関数）」）
// ---------------------------------------------------------------------------
function calcTax(discountedTotal: number): number {
  return Math.floor(discountedTotal * TAX_RATE);
}

// () を付けずに代入すると「関数そのもの」が入る
const taxCalculator = calcTax;

check('calcTax(3876)', calcTax(3876), 387);
check('taxCalculator(3876) も同じ結果', taxCalculator(3876), 387);
check('typeof calcTax', typeof calcTax, 'function');
check('同じ関数を指している', taxCalculator === calcTax, true);
check('() を付けて代入すると数値になる', typeof calcTax(3876), 'number');

// ---------------------------------------------------------------------------
// 2. 関数型の型注釈（本文「2. 関数型の型注釈」）
// ---------------------------------------------------------------------------
const half: (value: number) => number = (value) => Math.floor(value / 2);
check('half(4080)', half(4080), 2040);

// 型に書いた引数名と実装の引数名は一致しなくてよい
const perHundred: (subtotal: number) => number = (amount) => Math.floor(amount / 100);
check('引数名は型の一致に関係しない', perHundred(4080), 40);

// 引数を受け取らない関数も、引数1つの関数型の場所に入れられる
const noDiscountRule: (subtotal: number) => number = () => 0;
check('引数を使わない関数も渡せる', noDiscountRule(4080), 0);

// void を返す関数型（本文では console.log。ここでは結果を捕まえて検証する）
let lastLog = '';
const logLine: (message: string) => void = (message) => {
  lastLog = `[LOG] ${message}`;
};
logLine('割引を適用しました');
check('void を返す関数型', lastLog, '[LOG] 割引を適用しました');

// Good（型安全性の改善）：足りない情報は外側から与える
const goodPercent = 5;
const goodSilverRule: (subtotal: number) => number = (subtotal) =>
  Math.floor((subtotal * goodPercent) / 100);
check('外側の値を使う関数', goodSilverRule(4080), 204);

// ---------------------------------------------------------------------------
// 3. 高階関数とコールバック関数（本文「3. 高階関数 — 関数を引数に取る」）
// ---------------------------------------------------------------------------
function applyDiscountRule(subtotal: number, rule: (subtotal: number) => number): number {
  const amount = rule(subtotal);
  // 割引額が小計を超えないよう上限をかける（支払額をマイナスにしない）
  return Math.min(amount, subtotal);
}

const ruleNoDiscount = (): number => 0;
const ruleSilver = (subtotal: number): number => Math.floor((subtotal * 5) / 100);
const ruleBulk = (subtotal: number): number => (subtotal >= 5000 ? 500 : 0);
const ruleCoupon300 = (): number => 300;

check('割引なし', applyDiscountRule(4080, ruleNoDiscount), 0);
check('シルバー5%', applyDiscountRule(4080, ruleSilver), 204);
check('まとめ買い（5000円未満）', applyDiscountRule(4080, ruleBulk), 0);
check('まとめ買い（5000円以上）', applyDiscountRule(6000, ruleBulk), 500);
check('割引額は小計を超えない', applyDiscountRule(200, ruleCoupon300), 200);

// Bad 側の書き方（kind で分岐する版）でも同じ結果になることを確認しておく
function calcDiscountByKind(subtotal: number, kind: string): number {
  if (kind === 'silver') {
    return Math.floor((subtotal * 5) / 100);
  }
  if (kind === 'bulk') {
    return subtotal >= 5000 ? 500 : 0;
  }
  if (kind === 'coupon300') {
    return 300;
  }
  return 0;
}
check('Bad 版でも計算結果は同じ', calcDiscountByKind(4080, 'silver'), 204);
check('Bad 版は上限をかけていない', calcDiscountByKind(200, 'coupon300'), 300);

// コールバック関数（本文「コールバック関数」）
function repeat(times: number, callback: (index: number) => void): void {
  for (let i = 0; i < times; i += 1) {
    callback(i);
  }
}

let repeatOutput = '';
repeat(3, (index) => {
  const quantity = index + 1;
  repeatOutput += `${quantity}点：小計 ${1800 * quantity}円\n`;
});
check(
  'repeat の出力',
  repeatOutput,
  '1点：小計 1800円\n2点：小計 3600円\n3点：小計 5400円\n'
);

// ---------------------------------------------------------------------------
// 4. 関数を返す関数とクロージャ（本文「4. 関数を返す関数とクロージャ」）
// ---------------------------------------------------------------------------
function makePercentDiscount(percent: number): (subtotal: number) => number {
  return (subtotal: number): number => Math.floor((subtotal * percent) / 100);
}

const goldDiscount = makePercentDiscount(10);
const silverDiscount = makePercentDiscount(5);
check('gold 10%', goldDiscount(4080), 408);
check('silver 5%', silverDiscount(4080), 204);
check('別々に作った関数は互いに影響しない', goldDiscount(4080) - silverDiscount(4080), 204);

// 状態を閉じ込めるクロージャ
function createStockPicker(initialStock: number): () => number {
  let remaining = initialStock;

  return (): number => {
    if (remaining <= 0) {
      return 0;
    }
    remaining -= 1;
    return remaining;
  };
}

const pick = createStockPicker(3);
check('在庫ピッカー1回目', pick(), 2);
check('在庫ピッカー2回目', pick(), 1);
check('在庫ピッカー3回目', pick(), 0);
check('在庫ピッカー4回目（0で止まる）', pick(), 0);

const pickA = createStockPicker(2);
const pickB = createStockPicker(2);
check('A の1回目', pickA(), 1);
check('A の2回目', pickA(), 0);
check('B は A の影響を受けない', pickB(), 1);

// 4.4 ランクからルールを作って支払総額を求める（本文 src/session06/payable.ts）
function resolveMemberRank(totalPurchase: number): string {
  if (totalPurchase >= 50000) {
    return 'gold';
  }
  if (totalPurchase >= 20000) {
    return 'silver';
  }
  if (totalPurchase >= 5000) {
    return 'bronze';
  }
  return 'none';
}

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

function resolveDiscountRule(rank: string): (subtotal: number) => number {
  const percent = discountPercentByRank(rank);
  return (subtotal: number): number => Math.floor((subtotal * percent) / 100);
}

function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

function calcPayableAmount(subtotal: number, rule: (subtotal: number) => number): number {
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  const shippingFee = calcShippingFee(totalWithTax); // 手順6
  return totalWithTax + shippingFee; // 手順7
}

check('ランク（60000円）', resolveMemberRank(60000), 'gold');
check('ランク（25000円）', resolveMemberRank(25000), 'silver');
check('ランク（5000円ちょうど）', resolveMemberRank(5000), 'bronze');
check('ランク（1000円）', resolveMemberRank(1000), 'none');
check('割引率（gold）', discountPercentByRank('gold'), 10);
check('割引率（未知のランク）', discountPercentByRank('platinum'), 0);

// 本文の出力（gold / 4080 → 4039、none / 1440 → 2084、まとめ買い / 6000 → 6050）
check('gold・小計4080', calcPayableAmount(4080, resolveDiscountRule('gold')), 4039);
check('none・小計1440', calcPayableAmount(1440, resolveDiscountRule('none')), 2084);
check(
  'まとめ買い・小計6000',
  calcPayableAmount(6000, (subtotal) => (subtotal >= 5000 ? 500 : 0)),
  6050
);

// 計算手順を1ステップずつ検証する（gold・小計4080）
const stepSubtotal = 4080;
const stepDiscount = Math.floor((stepSubtotal * 10) / 100);
const stepDiscounted = stepSubtotal - stepDiscount;
const stepTax = Math.floor(stepDiscounted * TAX_RATE);
const stepTotalWithTax = stepDiscounted + stepTax;
check('手順2 割引額', stepDiscount, 408);
check('手順3 割引後小計', stepDiscounted, 3672);
check('手順4 消費税', stepTax, 367);
check('手順5 税込商品合計', stepTotalWithTax, 4039);
check('手順6 送料', calcShippingFee(stepTotalWithTax), 0);
check('手順7 支払総額', stepTotalWithTax + calcShippingFee(stepTotalWithTax), 4039);

// ---------------------------------------------------------------------------
// 5. 再帰関数（本文「5. 再帰関数」）
// ---------------------------------------------------------------------------
function sumDigits(value: number): number {
  if (value < 10) {
    return value;
  }
  return (value % 10) + sumDigits(Math.floor(value / 10));
}

check('sumDigits(4080)', sumDigits(4080), 12);
check('sumDigits(999)', sumDigits(999), 27);
check('sumDigits(7)', sumDigits(7), 7);
check('sumDigits(1440)', sumDigits(1440), 9);
check('sumDigits(0)', sumDigits(0), 0);

function applyCouponTimes(price: number, times: number): number {
  if (times <= 0) {
    return price;
  }
  const discounted = price - Math.floor((price * 5) / 100);
  return applyCouponTimes(discounted, times - 1);
}

check('クーポン0枚', applyCouponTimes(4080, 0), 4080);
check('クーポン1枚', applyCouponTimes(4080, 1), 3876);
check('クーポン2枚', applyCouponTimes(4080, 2), 3683);
check('クーポン3枚', applyCouponTimes(4080, 3), 3499);
check('負の枚数でも止まる', applyCouponTimes(4080, -1), 4080);
check('一律15%引き', 4080 - Math.floor((4080 * 15) / 100), 3468);
check('重ねがけとの差額', applyCouponTimes(4080, 3) - (4080 - Math.floor((4080 * 15) / 100)), 31);

function reverseText(text: string): string {
  if (text.length <= 1) {
    return text;
  }
  return reverseText(text.slice(1)) + text.slice(0, 1);
}

check('reverseText（商品名）', reverseText('ハンドクリーム'), 'ムーリクドンハ');
check('reverseText（1文字）', reverseText('あ'), 'あ');
check('reverseText（空文字）', reverseText(''), '');

// ---------------------------------------------------------------------------
// 6. 関数オーバーロード（本文「6. 関数オーバーロードの基本」）
// ---------------------------------------------------------------------------
function discountInfo(percent: number): string;
function discountInfo(percent: number, subtotal: number): number;
function discountInfo(percent: number, subtotal?: number): string | number {
  if (subtotal === undefined) {
    return `${percent}%OFF`;
  }
  return Math.floor((subtotal * percent) / 100);
}

// 型注釈付きの変数で受けることで、戻り値の型が呼び方ごとに変わることを確認する
const infoLabel: string = discountInfo(5);
const infoAmount: number = discountInfo(5, 4080);
check('discountInfo(5)', infoLabel, '5%OFF');
check('discountInfo(5, 4080)', infoAmount, 204);

// Good（保守性の改善）：戻り値の型が同じならユニオン型1本で足りる
function toYen(value: number | string): string {
  return `${value}円`;
}
check('toYen(4080)', toYen(4080), '4080円');
check("toYen('4,080')", toYen('4,080'), '4,080円');

// ---------------------------------------------------------------------------
// 7. アロー関数と this（本文「7. アロー関数と `this` の落とし穴」）
//    this を使わず引数で受け取る形（Good 側）だけを検証する。
// ---------------------------------------------------------------------------
const addTax = (total: number): number => Math.floor(total * TAX_RATE);
check('addTax(3876)', addTax(3876), 387);

// ---------------------------------------------------------------------------
// 8. 練習問題の解答（解答章の「期待される出力」と一致すること）
// ---------------------------------------------------------------------------

// 問題1：関数を値として持ち運ぶ
const q1ToLabel: (amount: number) => string = (amount) => `お支払い：${amount}円`;
check('問題1の1行目', `calcTax(3876) = ${calcTax(3876)}`, 'calcTax(3876) = 387');
check(
  '問題1の2行目',
  `taxCalculator(3876) = ${taxCalculator(3876)}`,
  'taxCalculator(3876) = 387'
);
check('問題1の3行目', `typeof calcTax = ${typeof calcTax}`, 'typeof calcTax = function');
check('問題1の4行目', q1ToLabel(4263), 'お支払い：4263円');

// 問題2：割引ルールを差し替える
const q2Bronze = (subtotal: number): number => Math.floor((subtotal * 3) / 100);
const q2Coupon300 = (): number => 300;
check('問題2 割引なし', applyDiscountRule(4080, ruleNoDiscount), 0);
check('問題2 ブロンズ3%', applyDiscountRule(4080, q2Bronze), 122);
check('問題2 300円クーポン', applyDiscountRule(4080, q2Coupon300), 300);
check('問題2 上限（小計200円）', applyDiscountRule(200, q2Coupon300), 200);
check(
  '問題2の2行目',
  `小計 4080円 / ブロンズ3%：${applyDiscountRule(4080, q2Bronze)}円`,
  '小計 4080円 / ブロンズ3%：122円'
);

// 問題3：再帰（sumDigits と applyCouponTimes は上で検証済み。出力行を確認する）
check('問題3の4行目', `クーポン3枚：${applyCouponTimes(4080, 3)}円`, 'クーポン3枚：3499円');
check('問題3の5行目', `クーポン0枚：${applyCouponTimes(4080, 0)}円`, 'クーポン0枚：4080円');

// 問題3 別解：ループ版でも同じ結果になる
function sumDigitsByLoop(value: number): number {
  let rest = value;
  let total = 0;
  while (rest > 0) {
    total += rest % 10;
    rest = Math.floor(rest / 10);
  }
  return total;
}
check('問題3 別解（4080）', sumDigitsByLoop(4080), 12);
check('問題3 別解（999）', sumDigitsByLoop(999), 27);
check('問題3 別解と再帰版が一致', sumDigitsByLoop(1440), sumDigits(1440));

// 問題4：クロージャ
function createCouponIssuer(limit: number): () => number {
  let remaining = limit;

  return (): number => {
    if (remaining <= 0) {
      return 0;
    }
    remaining -= 1;
    return remaining;
  };
}

function makeTaxCalculator(rate: number): (amount: number) => number {
  return (amount: number): number => Math.floor(amount * rate);
}

const issue = createCouponIssuer(3);
check('問題4の1行目', `1回目：残り${issue()}枚`, '1回目：残り2枚');
check('問題4の2行目', `2回目：残り${issue()}枚`, '2回目：残り1枚');
check('問題4の3行目', `3回目：残り${issue()}枚`, '3回目：残り0枚');
check('問題4の4行目', `4回目：残り${issue()}枚`, '4回目：残り0枚');

const issueOther = createCouponIssuer(5);
check('問題4の5行目', `別のクーポン：残り${issueOther()}枚`, '別のクーポン：残り4枚');

const calcTax10 = makeTaxCalculator(0.1);
const calcTax8 = makeTaxCalculator(0.08);
check('問題4の6行目', `税率10%：${calcTax10(3876)}円`, '税率10%：387円');
check('問題4の7行目', `税率8%：${calcTax8(3876)}円`, '税率8%：310円');
check('設定のクロージャは純粋関数', calcTax10(3876), calcTax10(3876));

// 問題5：ランク → ルール → 支払総額
function buildLine(totalPurchase: number, subtotal: number): string {
  const rank = resolveMemberRank(totalPurchase);
  const payable = calcPayableAmount(subtotal, resolveDiscountRule(rank));
  return `累計${totalPurchase}円 → ${rank} / 小計${subtotal}円 → お支払い${payable}円`;
}

check(
  '問題5の1行目',
  buildLine(60000, 4080),
  '累計60000円 → gold / 小計4080円 → お支払い4039円'
);
check(
  '問題5の2行目',
  buildLine(25000, 1440),
  '累計25000円 → silver / 小計1440円 → お支払い2004円'
);
check(
  '問題5の3行目',
  buildLine(1000, 1440),
  '累計1000円 → none / 小計1440円 → お支払い2084円'
);

// 問題5 解説の表（silver・小計1440 の各手順）
const s5Discount = Math.floor((1440 * 5) / 100);
const s5Discounted = 1440 - s5Discount;
const s5Tax = Math.floor(s5Discounted * TAX_RATE);
const s5TotalWithTax = s5Discounted + s5Tax;
check('問題5 割引額', s5Discount, 72);
check('問題5 割引後小計', s5Discounted, 1368);
check('問題5 消費税', s5Tax, 136);
check('問題5 税込商品合計', s5TotalWithTax, 1504);
check('問題5 送料（3000円未満）', calcShippingFee(s5TotalWithTax), 500);
check('問題5 支払総額', s5TotalWithTax + calcShippingFee(s5TotalWithTax), 2004);

// 問題5 別解：率を受け取る版
function calcPayableByPercent(subtotal: number, percent: number): number {
  const discountAmount = Math.floor((subtotal * percent) / 100);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  return totalWithTax + calcShippingFee(totalWithTax);
}
check('問題5 別解（gold・4080）', calcPayableByPercent(4080, discountPercentByRank('gold')), 4039);
check(
  '問題5 別解は模範解答と一致する',
  calcPayableByPercent(1440, discountPercentByRank('silver')),
  calcPayableAmount(1440, resolveDiscountRule('silver'))
);

// 問題6：関数オーバーロード
function quantityInfo(quantity: number): string;
function quantityInfo(quantity: number, unitPrice: number): number;
function quantityInfo(quantity: number, unitPrice?: number): string | number {
  if (unitPrice === undefined) {
    return `${quantity}点`;
  }
  return quantity * unitPrice;
}

const q6Label: string = quantityInfo(3);
const q6Subtotal: number = quantityInfo(3, 1800);
check('問題6の1行目', `toYen(4080) = ${toYen(4080)}`, 'toYen(4080) = 4080円');
check('問題6の2行目', `toYen('4,080') = ${toYen('4,080')}`, "toYen('4,080') = 4,080円");
check('問題6の3行目', `quantityInfo(3) = ${q6Label}`, 'quantityInfo(3) = 3点');
check('問題6の4行目', `quantityInfo(3, 1800) = ${q6Subtotal}`, 'quantityInfo(3, 1800) = 5400');
// 単価0円でも undefined 判定なら正しく動く（!unitPrice と書くと壊れる箇所）
check('問題6 単価0円', quantityInfo(3, 0), 0);

// 問題7：クーポン重ねがけシミュレータ
function createUseCounter(): () => number {
  let used = 0;

  return (): number => {
    used += 1;
    return used;
  };
}

const q7Subtotal = 4080;
const countUse = createUseCounter();
let q7Output = '';

repeat(4, (index) => {
  const price = applyCouponTimes(q7Subtotal, index);
  q7Output += `クーポン${index}枚：${price}円（判定${countUse()}回目）\n`;
});

const q7Flat = q7Subtotal - Math.floor((q7Subtotal * 15) / 100);
const q7Staged = applyCouponTimes(q7Subtotal, 3);
q7Output += `一律15%引きの場合：${q7Flat}円\n`;
q7Output += `段階的な重ねがけのほうが${q7Staged - q7Flat}円高くなります\n`;

const q7Expected =
  'クーポン0枚：4080円（判定1回目）\n' +
  'クーポン1枚：3876円（判定2回目）\n' +
  'クーポン2枚：3683円（判定3回目）\n' +
  'クーポン3枚：3499円（判定4回目）\n' +
  '一律15%引きの場合：3468円\n' +
  '段階的な重ねがけのほうが31円高くなります\n';
check('問題7の出力', q7Output, q7Expected);

// 問題7 解説：小計1440円のときの差額（解答章の⑤で提示した値）
const q7AltFlat = 1440 - Math.floor((1440 * 15) / 100);
check('問題7 小計1440の一律15%引き', q7AltFlat, 1224);
check('問題7 小計1440の重ねがけ3枚', applyCouponTimes(1440, 3), 1235);
check('問題7 小計1440の差額', applyCouponTimes(1440, 3) - q7AltFlat, 11);

console.log('session06: ok');
