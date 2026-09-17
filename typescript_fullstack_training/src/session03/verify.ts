/**
 * セッション3「条件分岐」の検証スクリプト。
 *
 * 本文（008）と練習問題の解答（010）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * 実行: docker compose exec ts npx tsx src/session03/verify.ts
 */

// ---------------------------------------------------------------------------
// 共通の定数（本書は金額を整数の円で扱う）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;
const DEFAULT_DISCOUNT_PERCENT = 5;

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
// 本文 1〜3節：if / else / else if と境界値
// ---------------------------------------------------------------------------

/** 税込商品合計から送料を求める（3000円以上で無料、未満は500円） */
function calcShippingFee(totalWithTax: number): number {
  if (totalWithTax >= FREE_SHIPPING_THRESHOLD) {
    return 0;
  }
  return SHIPPING_FEE;
}

/** 問題1：送料と支払い合計の表示行を組み立てる */
function formatShippingLine(totalWithTax: number): string {
  let shippingFee: number;
  if (totalWithTax >= FREE_SHIPPING_THRESHOLD) {
    shippingFee = 0;
  } else {
    shippingFee = SHIPPING_FEE;
  }
  const total = totalWithTax + shippingFee;
  return `税込商品合計: ${totalWithTax}円 / 送料: ${shippingFee}円 / お支払い合計: ${total}円`;
}

/** 本文：狭い条件から順に書いた else if の連鎖 */
function stockMessage(stock: number): string {
  if (stock === 0) {
    return '在庫切れです';
  }
  if (stock <= 5) {
    return `残りわずか（${stock}個）`;
  }
  return '在庫あり';
}

/** 本文 Bad：広い条件を先に書くと在庫切れの枝に到達しない */
function stockMessageBadOrder(stock: number): string {
  if (stock <= 5) {
    return `残りわずか（${stock}個）`;
  }
  if (stock === 0) {
    // ここには到達しない（本文で説明している到達不能な枝）
    return '在庫切れです';
  }
  return '在庫あり';
}

checkNumber('送料: 小計2500円は500円', calcShippingFee(2500), 500);
checkNumber('送料: 小計2999円は500円（境界の直前）', calcShippingFee(2999), 500);
checkNumber('送料: 小計3000円は0円（境界ちょうど）', calcShippingFee(3000), 0);
checkNumber('送料: 小計3001円は0円', calcShippingFee(3001), 0);

checkString(
  '問題1: 税込商品合計2500円の表示行',
  formatShippingLine(2500),
  '税込商品合計: 2500円 / 送料: 500円 / お支払い合計: 3000円'
);
checkString(
  '問題1: 税込商品合計2999円の表示行',
  formatShippingLine(2999),
  '税込商品合計: 2999円 / 送料: 500円 / お支払い合計: 3499円'
);
checkString(
  '問題1: 税込商品合計3000円の表示行',
  formatShippingLine(3000),
  '税込商品合計: 3000円 / 送料: 0円 / お支払い合計: 3000円'
);
checkString(
  '問題1: 税込商品合計3001円の表示行',
  formatShippingLine(3001),
  '税込商品合計: 3001円 / 送料: 0円 / お支払い合計: 3001円'
);

checkString('在庫メッセージ: 0個', stockMessage(0), '在庫切れです');
checkString('在庫メッセージ: 3個', stockMessage(3), '残りわずか（3個）');
checkString('在庫メッセージ: 10個', stockMessage(10), '在庫あり');
checkString(
  '在庫メッセージ Bad: 条件の順序を誤ると0個が「残りわずか」になる',
  stockMessageBadOrder(0),
  '残りわずか（0個）'
);

// ---------------------------------------------------------------------------
// 本文 4節・問題2：truthy / falsy
// ---------------------------------------------------------------------------

/** Bad：truthy 判定にすると在庫0が「未設定」扱いになる */
function describeStockByTruthiness(stock: number): string {
  if (stock) {
    return `残り${stock}個`;
  }
  return '在庫数は未設定です';
}

/** Good：判定したいこと（1個以上あるか）を条件式に書く */
function describeStock(stock: number): string {
  if (stock > 0) {
    return `残り${stock}個`;
  }
  return '在庫切れです';
}

/** Bad：truthy 判定では空白だけの入力が通ってしまう */
function describeProductNameByTruthiness(inputName: string): string {
  if (inputName) {
    return `商品名: ${inputName}`;
  }
  return '商品名を入力してください';
}

/** Good：trim してから空かどうかを判定する */
function describeProductName(inputName: string): string {
  const trimmedName = inputName.trim();
  if (trimmedName !== '') {
    return `商品名: ${trimmedName}`;
  }
  return '商品名を入力してください';
}

checkString(
  'truthy Bad: 在庫0が「未設定」になる',
  describeStockByTruthiness(0),
  '在庫数は未設定です'
);
checkString('truthy Bad: 在庫3は表示される', describeStockByTruthiness(3), '残り3個');
checkString('truthy Good: 在庫0は「在庫切れ」', describeStock(0), '在庫切れです');
checkString('truthy Good: 在庫3は「残り3個」', describeStock(3), '残り3個');

// 空白だけの名前でも truthy なので「未入力」と判定されない（末尾の空白を含む
// 文字列との比較は誤差が出やすいため、未入力メッセージにならないことを確認する）
checkBoolean(
  'truthy Bad: 空白だけの商品名が未入力と判定されない',
  describeProductNameByTruthiness('   ') !== '商品名を入力してください',
  true
);
checkString(
  'truthy Good: 空白だけの商品名は未入力扱い',
  describeProductName('   '),
  '商品名を入力してください'
);
checkString(
  'truthy Good: 前後の空白を取り除いて表示する',
  describeProductName(' マグカップ '),
  '商品名: マグカップ'
);

// falsy な値の一覧（本文の表と一致することを確認する）
checkBoolean('falsy: 0', Boolean(0), false);
checkBoolean('falsy: 空文字列', Boolean(''), false);
checkBoolean('falsy: NaN', Boolean(Number('あ')), false);
checkBoolean('truthy: 文字の 0', Boolean('0'), true);
checkBoolean('truthy: 文字の false', Boolean('false'), true);
checkBoolean('truthy: 半角スペース1つ', Boolean(' '), true);

// ---------------------------------------------------------------------------
// 本文 5節・問題3：switch
// ---------------------------------------------------------------------------

/** 本文：let + break の形（default で想定外を受ける） */
function describeOrderStatusWithBreak(status: string): string {
  let message: string;
  switch (status) {
    case 'pending':
      message = 'お支払いをお待ちしています';
      break;
    case 'paid':
      message = 'お支払いを確認しました。発送準備中です';
      break;
    case 'shipped':
      message = '発送済みです';
      break;
    case 'cancelled':
      message = 'キャンセルされました';
      break;
    default:
      message = '不明なステータスです';
  }
  return message;
}

/** 本文 Bad：break を書き忘れると次の case に流れ込む（フォールスルー） */
function describeOrderStatusBuggy(status: string): string {
  let message: string;
  switch (status) {
    case 'pending':
      message = 'お支払いをお待ちしています';
    // ここで break を書き忘れているため、次の case が続けて実行される
    case 'paid':
      message = 'お支払いを確認しました。発送準備中です';
      break;
    case 'shipped':
      message = '発送済みです';
      break;
    default:
      message = '不明なステータスです';
  }
  return message;
}

/** 本文 8節・問題3：return を使う形（break が不要になる） */
function describeOrderStatus(status: string): string {
  switch (status) {
    case 'pending':
      return 'お支払いをお待ちしています';
    case 'paid':
      return 'お支払いを確認しました。発送準備中です';
    case 'shipped':
      return '発送済みです';
    case 'cancelled':
      return 'キャンセルされました';
    default:
      return '不明なステータスです';
  }
}

/** 問題3：発送前（pending / paid）だけキャンセルできる（case のまとめ書き） */
function canCancelOrder(status: string): boolean {
  switch (status) {
    case 'pending':
    case 'paid':
      return true;
    case 'shipped':
    case 'cancelled':
      return false;
    default:
      // 知らないステータスは安全側に倒してキャンセル不可とする
      return false;
  }
}

checkString(
  'switch(break版): paid',
  describeOrderStatusWithBreak('paid'),
  'お支払いを確認しました。発送準備中です'
);
checkString(
  'switch(break版): 未知のステータスは default に落ちる',
  describeOrderStatusWithBreak('refunded'),
  '不明なステータスです'
);
checkString(
  'switch Bad: break 忘れで pending が paid の文言になる',
  describeOrderStatusBuggy('pending'),
  'お支払いを確認しました。発送準備中です'
);

checkString(
  '問題3: pending',
  describeOrderStatus('pending'),
  'お支払いをお待ちしています'
);
checkString(
  '問題3: paid',
  describeOrderStatus('paid'),
  'お支払いを確認しました。発送準備中です'
);
checkString('問題3: shipped', describeOrderStatus('shipped'), '発送済みです');
checkString('問題3: cancelled', describeOrderStatus('cancelled'), 'キャンセルされました');
checkString('問題3: refunded', describeOrderStatus('refunded'), '不明なステータスです');

checkBoolean('問題3: pending はキャンセル可', canCancelOrder('pending'), true);
checkBoolean('問題3: paid はキャンセル可', canCancelOrder('paid'), true);
checkBoolean('問題3: shipped はキャンセル不可', canCancelOrder('shipped'), false);
checkBoolean('問題3: cancelled はキャンセル不可', canCancelOrder('cancelled'), false);
checkBoolean('問題3: refunded はキャンセル不可', canCancelOrder('refunded'), false);

// ---------------------------------------------------------------------------
// 本文 6節：三項演算子
// ---------------------------------------------------------------------------

/** 三項演算子で送料を求める（if / else 版と同じ結果になる） */
function calcShippingFeeByTernary(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

/** テンプレートリテラルの中で三項演算子を使う */
function formatStockLabel(stock: number): string {
  return `この商品は${stock > 0 ? '在庫あり' : '在庫切れ'}です`;
}

/** 本文 Bad/Good：会員ランクを else if の連鎖で求める */
function resolveMemberRankByElseIf(totalSpent: number): string {
  let rank: string;
  if (totalSpent >= 50000) {
    rank = 'gold';
  } else if (totalSpent >= 20000) {
    rank = 'silver';
  } else if (totalSpent >= 5000) {
    rank = 'bronze';
  } else {
    rank = 'none';
  }
  return rank;
}

checkNumber('三項演算子: 小計2500円は送料500円', calcShippingFeeByTernary(2500), 500);
checkNumber('三項演算子: 小計3000円は送料0円', calcShippingFeeByTernary(3000), 0);
checkString('三項演算子: 在庫0のラベル', formatStockLabel(0), 'この商品は在庫切れです');
checkString('三項演算子: 在庫2のラベル', formatStockLabel(2), 'この商品は在庫ありです');
checkString('else if: 累計23000円は silver', resolveMemberRankByElseIf(23000), 'silver');

// ---------------------------------------------------------------------------
// 本文 7節・問題4：?? と || の違い
// ---------------------------------------------------------------------------

/** ?? を使う版。null / undefined のときだけ既定値になる */
function resolveDiscountPercent(inputPercent: number): number {
  return inputPercent ?? DEFAULT_DISCOUNT_PERCENT;
}

/** || を使う版。falsy（0 を含む）で既定値になってしまう */
function resolveDiscountPercentWithOr(inputPercent: number): number {
  return inputPercent || DEFAULT_DISCOUNT_PERCENT;
}

/** 割引率を表示用の文字列にする（三項演算子） */
function formatDiscountLabel(percent: number): string {
  return percent === 0 ? '割引なし' : `${percent}%OFF`;
}

/** ?? では空文字列を弾けないことを示す比較用 */
function resolveProductNameWithNullish(inputName: string): string {
  return inputName ?? '(名称未設定)';
}

/** || では空白だけの文字列を弾けないことを示す比較用 */
function resolveProductNameWithOr(inputName: string): string {
  return inputName || '(名称未設定)';
}

/** 問題4：trim してから空かどうかを判定する */
function resolveProductName(inputName: string): string {
  const trimmed = inputName.trim();
  return trimmed === '' ? '(名称未設定)' : trimmed;
}

checkNumber('?? に 0 を渡すと 0 のまま', resolveDiscountPercent(0), 0);
checkNumber('?? に 10 を渡すと 10', resolveDiscountPercent(10), 10);
checkNumber('|| に 0 を渡すと既定値 5 に化ける', resolveDiscountPercentWithOr(0), 5);
checkNumber('|| に 10 を渡すと 10', resolveDiscountPercentWithOr(10), 10);

checkString('三項演算子: 割引率0のラベル', formatDiscountLabel(0), '割引なし');
checkString('三項演算子: 割引率5のラベル', formatDiscountLabel(5), '5%OFF');
checkString('三項演算子: 割引率10のラベル', formatDiscountLabel(10), '10%OFF');

checkString('?? では空文字列は置き換わらない', resolveProductNameWithNullish(''), '');
checkString('|| では空文字列が置き換わる', resolveProductNameWithOr(''), '(名称未設定)');
checkString('|| では空白だけの文字列は置き換わらない', resolveProductNameWithOr('   '), '   ');
checkString('問題4: 空白だけの商品名', resolveProductName('   '), '(名称未設定)');
checkString('問題4: 前後に空白のある商品名', resolveProductName(' マグカップ '), 'マグカップ');

// undefined のときは ?? と || の結果が一致する（本文の表と対応）
const enteredNickname = undefined; // ニックネームが未入力の状態
const nicknameByNullish = enteredNickname ?? 'ゲスト';
const nicknameByOr = enteredNickname || 'ゲスト';
checkString('?? に undefined を渡すと既定値', nicknameByNullish, 'ゲスト');
checkString('|| に undefined を渡しても既定値', nicknameByOr, 'ゲスト');

// ---------------------------------------------------------------------------
// 本文 8節：関数の最小限とガード節
// ---------------------------------------------------------------------------

/** 本文 Good：ガード節で特別なケースを入り口で片付ける */
function calcAmountToPay(subtotal: number, isMember: boolean): number {
  // ガード節：カートが空なら支払いは発生しない
  if (subtotal <= 0) {
    return 0;
  }

  // ここから下は「商品が入っているカート」だけを考えればよい
  const discountPercent = isMember ? 5 : 0;
  const discounted = subtotal - Math.floor((subtotal * discountPercent) / 100);
  const totalWithTax = discounted + Math.floor(discounted * TAX_RATE);
  return totalWithTax + calcShippingFee(totalWithTax);
}

checkNumber('ガード節: 2000円・会員（割引100円→税込2090円→送料500円）', calcAmountToPay(2000, true), 2590);
checkNumber('ガード節: 4000円・非会員（税込4400円→送料無料）', calcAmountToPay(4000, false), 4400);
checkNumber('ガード節: 空のカートは0円', calcAmountToPay(0, true), 0);

// ---------------------------------------------------------------------------
// 問題5：会員ランクと支払い金額
// ---------------------------------------------------------------------------

/** 累計購入額から会員ランクを求める（ガード節で else を使わない） */
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

/** 会員ランクに応じた割引率（%） */
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

/** 支払い金額（税込商品合計 + 送料）を求める */
function calcPayableAmount(subtotal: number, totalSpent: number): number {
  // ガード節：カートが空なら支払いは発生しない
  if (subtotal <= 0) {
    return 0;
  }

  const rank = resolveMemberRank(totalSpent);
  const discountPercent = discountPercentByRank(rank);

  // 金額は整数の円で扱う。割引額は切り捨て
  const discount = Math.floor((subtotal * discountPercent) / 100);
  const discountedSubtotal = subtotal - discount;

  const tax = Math.floor(discountedSubtotal * TAX_RATE);
  const totalWithTax = discountedSubtotal + tax;

  // 送料は「税込商品合計」で判定する（本書の共通ルール）
  const shippingFee = calcShippingFee(totalWithTax);

  return totalWithTax + shippingFee;
}

checkString('問題5: 累計60000円は gold', resolveMemberRank(60000), 'gold');
checkString('問題5: 累計50000円は gold（境界ちょうど）', resolveMemberRank(50000), 'gold');
checkString('問題5: 累計20000円は silver', resolveMemberRank(20000), 'silver');
checkString('問題5: 累計6000円は bronze', resolveMemberRank(6000), 'bronze');
checkString('問題5: 累計4999円は none', resolveMemberRank(4999), 'none');

checkNumber('問題5: gold の割引率', discountPercentByRank('gold'), 10);
checkNumber('問題5: silver の割引率', discountPercentByRank('silver'), 5);
checkNumber('問題5: bronze の割引率', discountPercentByRank('bronze'), 3);
checkNumber('問題5: 未知のランクは割引0%', discountPercentByRank('platinum'), 0);

checkNumber('問題5: 10000円・gold', calcPayableAmount(10000, 60000), 9900);
checkNumber('問題5: 5000円・silver', calcPayableAmount(5000, 20000), 5225);
checkNumber('問題5: 3200円・bronze', calcPayableAmount(3200, 6000), 3414);
checkNumber('問題5: 3050円・bronze（税抜2959円だが税込3254円で送料無料）', calcPayableAmount(3050, 6000), 3254);
checkNumber('問題5: 3000円・gold（割引で税込2970円まで下がり送料が発生）', calcPayableAmount(3000, 60000), 3470);
checkNumber('問題5: 2000円・none', calcPayableAmount(2000, 0), 2700);
checkNumber('問題5: 空のカート', calcPayableAmount(0, 60000), 0);

// ---------------------------------------------------------------------------
// 問題6：注文ステータスの遷移
// ---------------------------------------------------------------------------

function canTransitionTo(current: string, next: string): boolean {
  // ガード節：同じステータスへは移れない
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
      // 発送済み・キャンセル済みは終着点
      return false;
    default:
      // 知らないステータスは許可しない
      return false;
  }
}

checkBoolean('問題6: pending → paid', canTransitionTo('pending', 'paid'), true);
checkBoolean('問題6: pending → cancelled', canTransitionTo('pending', 'cancelled'), true);
checkBoolean('問題6: pending → shipped', canTransitionTo('pending', 'shipped'), false);
checkBoolean('問題6: paid → shipped', canTransitionTo('paid', 'shipped'), true);
checkBoolean('問題6: paid → pending', canTransitionTo('paid', 'pending'), false);
checkBoolean('問題6: shipped → cancelled', canTransitionTo('shipped', 'cancelled'), false);
checkBoolean('問題6: paid → paid', canTransitionTo('paid', 'paid'), false);
checkBoolean('問題6: refunded → paid', canTransitionTo('refunded', 'paid'), false);

// ---------------------------------------------------------------------------
// 問題7：注文確認メッセージの組み立て
// ---------------------------------------------------------------------------

function buildOrderSummary(status: string, subtotal: number, totalSpent: number): string {
  // ガード節：カートが空なら金額の話をする必要がない
  if (subtotal <= 0) {
    return 'カートに商品がありません';
  }

  const payableAmount = calcPayableAmount(subtotal, totalSpent);
  const statusMessage = describeOrderStatus(status);
  const cancelLabel = canCancelOrder(status) ? 'キャンセル可能' : 'キャンセル不可';

  return `${statusMessage} / お支払い金額: ${payableAmount}円 / ${cancelLabel}`;
}

checkString(
  '問題7: paid / 10000円 / 累計60000円',
  buildOrderSummary('paid', 10000, 60000),
  'お支払いを確認しました。発送準備中です / お支払い金額: 9900円 / キャンセル可能'
);
checkString(
  '問題7: shipped / 2000円 / 累計0円',
  buildOrderSummary('shipped', 2000, 0),
  '発送済みです / お支払い金額: 2700円 / キャンセル不可'
);
checkString(
  '問題7: refunded / 5000円 / 累計20000円',
  buildOrderSummary('refunded', 5000, 20000),
  '不明なステータスです / お支払い金額: 5225円 / キャンセル不可'
);
checkString(
  '問題7: 空のカート',
  buildOrderSummary('pending', 0, 0),
  'カートに商品がありません'
);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session03: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session03: ok');
