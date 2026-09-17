/**
 * セッション7「配列とタプル」の検証スクリプト。
 *
 * 本文（020）と練習問題の解答（022）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * console.log を1行ずつ出す章のコードは、この検証では
 * 「出力行を \n でつないだ文字列」を返す関数として表現している。
 *
 * 実行: docker compose exec ts npx tsx src/session07/verify.ts
 */

import { inspect } from 'node:util';

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
// 本文 1節：配列を作る・読む（src/session07/array-basics.ts）
// ---------------------------------------------------------------------------
function bodyArrayBasics(): string {
  const productNames: string[] = ['ラベンダーの石けん', 'ハンドクリーム', 'マグカップ'];
  const unitPrices: Array<number> = [480, 1800, 2350];

  const lines: string[] = [];
  lines.push(String(productNames.length));
  lines.push(String(productNames[0]));
  lines.push(String(productNames[2]));
  lines.push(String(unitPrices[1]));
  // console.log(unitPrices) の表示（Node は util.inspect で整形する）
  lines.push(inspect(unitPrices));
  return lines.join('\n');
}

checkString(
  '本文1節: 配列の宣言と読み取り',
  bodyArrayBasics(),
  '3\nラベンダーの石けん\nマグカップ\n1800\n[ 480, 1800, 2350 ]'
);

// 空配列の length は 0
const bodyEmptyCart: string[] = [];
checkNumber('本文1節: 空配列の length', bodyEmptyCart.length, 0);

// ---------------------------------------------------------------------------
// 本文 2節：範囲外アクセスと noUncheckedIndexedAccess
// ---------------------------------------------------------------------------
const bodyNames: string[] = ['ラベンダーの石けん', 'ハンドクリーム', 'マグカップ'];

// 範囲外アクセスは undefined になる（実行時の挙動は設定に関係なく同じ）
checkBoolean('本文2節: 範囲外アクセスは undefined', bodyNames[3] === undefined, true);
checkBoolean('本文2節: 0番は存在する', bodyNames[0] === 'ラベンダーの石けん', true);

/** 対処法1：for...of なら name は string（undefined が混ざらない） */
function bodyForOfSafe(names: readonly string[]): string {
  let log = '';
  for (const name of names) {
    log += `${name}（${name.length}文字）\n`;
  }
  return log;
}

checkString(
  '本文2節: for...of で走査する',
  bodyForOfSafe(bodyNames),
  'ラベンダーの石けん（9文字）\nハンドクリーム（7文字）\nマグカップ（5文字）\n'
);

/** 対処法2：取り出した直後にガード節で undefined を弾く */
function describeProduct(names: string[], index: number): string {
  const name = names[index];

  if (name === undefined) {
    return `${index}番の商品はありません`;
  }

  return `${index}番: ${name}（${name.length}文字）`;
}

checkString(
  '本文2節: ガード節あり（存在する番号）',
  describeProduct(bodyNames, 0),
  '0番: ラベンダーの石けん（9文字）'
);
checkString(
  '本文2節: ガード節あり（範囲外の番号）',
  describeProduct(bodyNames, 3),
  '3番の商品はありません'
);

/** 対処法3：at() と ?? を組み合わせる */
function bodyAtAndNullish(): string {
  const unitPrices: number[] = [480, 1800, 2350];

  const lastPrice = unitPrices.at(-1) ?? 0;
  const missingPrice = unitPrices.at(99) ?? 0;

  const lines: string[] = [];
  lines.push(String(unitPrices.at(0)));
  lines.push(String(unitPrices.at(-1)));
  lines.push(String(unitPrices.at(99)));
  lines.push(String(lastPrice + missingPrice));
  return lines.join('\n');
}

checkString('本文2節: at() の挙動', bodyAtAndNullish(), '480\n2350\nundefined\n2350');

// at(-1) は「末尾」を意味する。length - 1 と同じ結果になることも確認する
const bodyPrices: number[] = [480, 1800, 2350];
const bodyLastByIndex = bodyPrices[bodyPrices.length - 1] ?? 0;
checkNumber('本文2節: at(-1) と length - 1 は同じ', bodyPrices.at(-1) ?? 0, bodyLastByIndex);

// ---------------------------------------------------------------------------
// 本文 3節：破壊的なメソッド（src/session07/cart-mutate.ts / splice.ts）
// ---------------------------------------------------------------------------
function bodyCartMutate(): string {
  const cartNames: string[] = [];

  const lines: string[] = [];
  lines.push(String(cartNames.push('ラベンダーの石けん')));

  cartNames.push('ハンドクリーム');
  cartNames.push('マグカップ');
  lines.push(String(cartNames.length));
  lines.push(cartNames.join(' / '));

  const removed = cartNames.pop();
  lines.push(String(removed));
  lines.push(cartNames.join(' / '));

  const empty: string[] = [];
  lines.push(String(empty.pop()));
  return lines.join('\n');
}

checkString(
  '本文3節: push と pop',
  bodyCartMutate(),
  '1\n' +
    '3\n' +
    'ラベンダーの石けん / ハンドクリーム / マグカップ\n' +
    'マグカップ\n' +
    'ラベンダーの石けん / ハンドクリーム\n' +
    'undefined'
);

function bodySplice(): string {
  const cartNames: string[] = [
    'ラベンダーの石けん',
    'ハンドクリーム',
    'マグカップ',
    'リネンのふきん',
  ];

  const lines: string[] = [];

  const removedItems = cartNames.splice(1, 1);
  lines.push(removedItems.join(' / '));
  lines.push(cartNames.join(' / '));

  cartNames.splice(1, 1, 'ミニタオル', 'アロマキャンドル');
  lines.push(cartNames.join(' / '));

  cartNames.splice(0, 0, 'ギフトボックス');
  lines.push(String(cartNames.length));
  lines.push(cartNames.join(' / '));
  return lines.join('\n');
}

checkString(
  '本文3節: splice で取り除く・差し込む',
  bodySplice(),
  'ハンドクリーム\n' +
    'ラベンダーの石けん / マグカップ / リネンのふきん\n' +
    'ラベンダーの石けん / ミニタオル / アロマキャンドル / リネンのふきん\n' +
    '5\n' +
    'ギフトボックス / ラベンダーの石けん / ミニタオル / アロマキャンドル / リネンのふきん'
);

// 第2引数を省略すると開始位置から末尾まで消える（alert の裏付け）
const bodySpliceAll: string[] = ['a', 'b', 'c'];
bodySpliceAll.splice(1);
checkString('本文3節: splice(1) は1番以降を全削除', bodySpliceAll.join(','), 'a');

/** indexOf + splice で「名前を指定して取り除く」 */
function removeFromCart(cart: string[], name: string): boolean {
  const index = cart.indexOf(name);

  if (index === -1) {
    return false;
  }

  cart.splice(index, 1);
  return true;
}

function bodyRemoveFromCart(): string {
  const cartNames: string[] = ['ラベンダーの石けん', 'ハンドクリーム', 'マグカップ'];

  const lines: string[] = [];
  lines.push(String(removeFromCart(cartNames, 'ハンドクリーム')));
  lines.push(cartNames.join(' / '));
  lines.push(String(removeFromCart(cartNames, '入浴剤')));
  // 見つからなければ何も取り除かない（件数は変わらない）
  checkNumber('本文3節: 見つからない場合は件数が変わらない', cartNames.length, 2);
  return lines.join('\n');
}

checkString(
  '本文3節: indexOf + splice で取り除く',
  bodyRemoveFromCart(),
  'true\nラベンダーの石けん / マグカップ\nfalse'
);

// ---------------------------------------------------------------------------
// 本文 4節：非破壊的なメソッド（src/session07/non-destructive.ts / reverse-pair.ts）
// ---------------------------------------------------------------------------
function bodyNonDestructive(): string {
  const allNames: string[] = [
    'ラベンダーの石けん',
    'ハンドクリーム',
    'マグカップ',
    'リネンのふきん',
  ];
  const newArrivals: string[] = ['アロマキャンドル', 'ギフトボックス'];
  const merged = allNames.concat(newArrivals);

  const lines: string[] = [];
  lines.push(allNames.slice(0, 2).join(' / '));
  lines.push(allNames.slice(2).join(' / '));
  lines.push(allNames.slice(-1).join(' / '));
  lines.push(String(allNames.length));
  lines.push(String(merged.length));
  lines.push(String(allNames.length));
  return lines.join('\n');
}

checkString(
  '本文4節: slice と concat は非破壊',
  bodyNonDestructive(),
  'ラベンダーの石けん / ハンドクリーム\nマグカップ / リネンのふきん\nリネンのふきん\n4\n6\n4'
);

function bodyReversePair(): string {
  const prices: number[] = [480, 1800, 2350];

  const lines: string[] = [];
  const reversedCopy = prices.toReversed();
  lines.push(reversedCopy.join(' / '));
  lines.push(prices.join(' / '));

  prices.reverse();
  lines.push(prices.join(' / '));
  return lines.join('\n');
}

checkString(
  '本文4節: toReversed は非破壊 / reverse は破壊的',
  bodyReversePair(),
  '2350 / 1800 / 480\n480 / 1800 / 2350\n2350 / 1800 / 480'
);

// ---------------------------------------------------------------------------
// 本文 5節：探す（src/session07/find-index.ts）
// ---------------------------------------------------------------------------
function bodyFindIndex(): string {
  const productNames: string[] = ['ラベンダーの石けん', 'ハンドクリーム', 'マグカップ'];

  const lines: string[] = [];
  lines.push(String(productNames.indexOf('ハンドクリーム')));
  lines.push(String(productNames.indexOf('入浴剤')));
  lines.push(String(productNames.includes('マグカップ')));
  lines.push(String(productNames.includes('入浴剤')));
  return lines.join('\n');
}

checkString('本文5節: indexOf と includes', bodyFindIndex(), '1\n-1\ntrue\nfalse');

// ---------------------------------------------------------------------------
// 本文 6節：readonly 配列（src/session07/readonly-array.ts）
// ---------------------------------------------------------------------------
const BODY_MASTER_PRICES: readonly number[] = [480, 1800, 2350, 990];

function bodyReadonlyArray(): string {
  const lines: string[] = [];
  lines.push(String(BODY_MASTER_PRICES.length));
  lines.push(String(BODY_MASTER_PRICES.at(-1)));
  lines.push(BODY_MASTER_PRICES.slice(0, 2).join(' / '));
  lines.push(String(BODY_MASTER_PRICES.indexOf(1800)));
  return lines.join('\n');
}

checkString('本文6節: readonly でも読む操作は使える', bodyReadonlyArray(), '4\n990\n480 / 1800\n1');

// const だけでは中身の書き換えを止められない（よくある誤解の裏付け）
const bodyConstButMutable: number[] = [480, 1800, 2350, 990];
bodyConstButMutable.push(0);
checkNumber('誤解の確認: const の配列は push できる', bodyConstButMutable.length, 5);

/** 読むだけの関数は readonly で受け取る */
function sumPrices(prices: readonly number[]): number {
  let total = 0;
  for (const price of prices) {
    total += price;
  }
  return total;
}

const bodyCartPrices: number[] = [480, 1800];
checkNumber('本文6節: readonly 引数に number[] を渡せる', sumPrices(bodyCartPrices), 2280);
checkNumber('本文6節: 渡した配列は変わらない', bodyCartPrices.length, 2);

// ---------------------------------------------------------------------------
// 本文 7節：タプル型（src/session07/tuple-basics.ts / tuple-label.ts / tuple-result.ts）
// ---------------------------------------------------------------------------
function bodyTupleBasics(): string {
  const nameAndPrice: [string, number] = ['ハンドクリーム', 1800];

  const lines: string[] = [];
  lines.push(nameAndPrice[0]);
  lines.push(String(nameAndPrice[1]));
  lines.push(String(nameAndPrice.length));
  // タプルなので ?? もガード節も不要（型は string / number で確定している）
  lines.push(String(nameAndPrice[0].length));
  lines.push(String(nameAndPrice[1] * 2));
  return lines.join('\n');
}

checkString('本文7節: タプルの読み取り', bodyTupleBasics(), 'ハンドクリーム\n1800\n2\n7\n3600');

// タプルは push で伸ばせてしまう（alert の裏付け）
const bodyTuplePush: [string, number] = ['ハンドクリーム', 1800];
bodyTuplePush.push(3);
checkNumber('誤解の確認: タプルは push で3件になる', bodyTuplePush.length, 3);

function bodyTupleLabel(): string {
  const boxSize: [width: number, height: number] = [24, 18];
  return `幅 ${boxSize[0]}cm × 高さ ${boxSize[1]}cm\n面積 ${boxSize[0] * boxSize[1]}平方cm`;
}

checkString('本文7節: ラベル付きタプル', bodyTupleLabel(), '幅 24cm × 高さ 18cm\n面積 432平方cm');

/** 在庫を確認して「注文できるか」と「メッセージ」を同時に返す */
function checkStock(stock: number, quantity: number): [ok: boolean, message: string] {
  if (quantity <= 0) {
    return [false, '数量を1点以上にしてください'];
  }
  if (stock <= 0) {
    return [false, '在庫切れです'];
  }
  if (stock < quantity) {
    return [false, `在庫が${stock}点しかありません`];
  }
  return [true, `${quantity}点を注文できます`];
}

function bodyTupleResult(): string {
  const result = checkStock(3, 5);
  const ok = checkStock(12, 2);

  const lines: string[] = [];
  lines.push(String(result[0]));
  lines.push(result[1]);
  lines.push(`${ok[0]} / ${ok[1]}`);
  return lines.join('\n');
}

checkString(
  '本文7節: タプルで2つの値を返す',
  bodyTupleResult(),
  'false\n在庫が3点しかありません\ntrue / 2点を注文できます'
);

// ---------------------------------------------------------------------------
// 本文 8節：多次元配列とタプルの配列（src/session07/matrix.ts / cart-lines.ts）
// ---------------------------------------------------------------------------
function bodyMatrix(): string {
  const namesByCategory: string[][] = [
    ['ラベンダーの石けん', 'ハンドクリーム'],
    ['マグカップ', 'リネンのふきん'],
    [],
  ];

  const lines: string[] = [];
  lines.push(String(namesByCategory.length));
  for (const items of namesByCategory) {
    lines.push(`${items.join(' / ')}（${items.length}件）`);
  }
  return lines.join('\n');
}

checkString(
  '本文8節: 多次元配列を二重の for...of で回す',
  bodyMatrix(),
  '3\n' +
    'ラベンダーの石けん / ハンドクリーム（2件）\n' +
    'マグカップ / リネンのふきん（2件）\n' +
    '（0件）'
);

/** 全カテゴリの商品数を数える（for...of だけで足りる） */
function countAll(matrix: readonly string[][]): number {
  let count = 0;
  for (const items of matrix) {
    count += items.length;
  }
  return count;
}

function bodyGoodMatrix(): string {
  const namesByCategory: string[][] = [['ラベンダーの石けん', 'ハンドクリーム'], []];

  const lines: string[] = [];
  const firstCategory = namesByCategory[0];
  if (firstCategory === undefined) {
    lines.push('そのカテゴリはありません');
  } else {
    lines.push(firstCategory.join(' / '));
  }
  lines.push(String(countAll(namesByCategory)));
  return lines.join('\n');
}

checkString(
  '本文8節: 一段ずつ取り出してガードする',
  bodyGoodMatrix(),
  'ラベンダーの石けん / ハンドクリーム\n2'
);

// 本文 8節：タプルの配列でカートを表す
function calcSubtotal(lines: readonly [string, number, number][]): number {
  let subtotal = 0;
  for (const line of lines) {
    subtotal += line[1] * line[2];
  }
  return subtotal;
}

function calcShippingFee(totalWithTax: number): number {
  return totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
}

function calcPayableAmount(subtotal: number, rule: (subtotal: number) => number): number {
  const discountAmount = Math.min(rule(subtotal), subtotal); // 手順2
  const discountedTotal = subtotal - discountAmount; // 手順3
  const tax = Math.floor(discountedTotal * TAX_RATE); // 手順4
  const totalWithTax = discountedTotal + tax; // 手順5
  return totalWithTax + calcShippingFee(totalWithTax); // 手順6・7
}

const noDiscount = (): number => 0;
const bronzeRule = (subtotal: number): number => Math.floor((subtotal * 3) / 100);
const goldRule = (subtotal: number): number => Math.floor((subtotal * 10) / 100);

function bodyCartLines(): string {
  const cartLines: [name: string, unitPrice: number, quantity: number][] = [
    ['ラベンダーの石けん', 480, 2],
    ['ハンドクリーム', 1800, 1],
  ];

  const lines: string[] = [];
  for (const line of cartLines) {
    lines.push(`${line[0]} ${line[1]}円 × ${line[2]}点 = ${line[1] * line[2]}円`);
  }
  lines.push(`明細 ${cartLines.length}件 / 小計 ${calcSubtotal(cartLines)}円`);
  return lines.join('\n');
}

checkString(
  '本文8節: タプルの配列で明細と小計を出す',
  bodyCartLines(),
  'ラベンダーの石けん 480円 × 2点 = 960円\n' +
    'ハンドクリーム 1800円 × 1点 = 1800円\n' +
    '明細 2件 / 小計 2760円'
);

// 本文8節で触れた「割引すると送料が発生して支払総額が上がる」ケースの裏付け
checkNumber('本文8節: 割引なしの支払総額', calcPayableAmount(2760, noDiscount), 3036);
checkNumber('本文8節: ブロンズ3%の支払総額', calcPayableAmount(2760, bronzeRule), 3445);
checkNumber('本文8節: 割引なしの税込商品合計', 2760 + Math.floor(2760 * TAX_RATE), 3036);
checkBoolean('本文8節: 割引後は3000円未満になる', 2966 >= FREE_SHIPPING_THRESHOLD, false);

// ---------------------------------------------------------------------------
// 問題1：商品リストを作って読む
// ---------------------------------------------------------------------------
function solveQ1(): string {
  const productNames: string[] = [
    'ラベンダーの石けん',
    'ハンドクリーム',
    'マグカップ',
    'リネンのふきん',
  ];
  const unitPrices: Array<number> = [480, 1800, 2350, 990];
  const NOT_FOUND_LABEL = '(該当なし)';

  let totalPrice = 0;
  for (const price of unitPrices) {
    totalPrice += price;
  }

  const lines: string[] = [];
  lines.push(`商品数: ${productNames.length}点`);
  lines.push(`最初の商品: ${productNames[0] ?? NOT_FOUND_LABEL}`);
  lines.push(`最後の単価: ${unitPrices.at(-1) ?? 0}円`);
  lines.push(`4番の商品: ${productNames[4] ?? NOT_FOUND_LABEL}`);
  lines.push(`単価の合計: ${totalPrice}円`);
  return lines.join('\n');
}

checkString(
  '問題1: 出力5行',
  solveQ1(),
  '商品数: 4点\n' +
    '最初の商品: ラベンダーの石けん\n' +
    '最後の単価: 990円\n' +
    '4番の商品: (該当なし)\n' +
    '単価の合計: 5620円'
);

// ---------------------------------------------------------------------------
// 問題2：カートに入れる・取り消す
// ---------------------------------------------------------------------------
function solveQ2(): string {
  const cart: string[] = [];

  const lines: string[] = [];
  const lengthAfterFirstPush = cart.push('ラベンダーの石けん');
  lines.push(`1点目を追加: 要素数${lengthAfterFirstPush}`);

  cart.push('ハンドクリーム');
  cart.push('マグカップ');
  lines.push(`追加後: ${cart.join(' / ')}（${cart.length}点）`);

  const removed = cart.pop();
  lines.push(`取り消した商品: ${removed ?? '(なし)'}（残り${cart.length}点）`);

  cart.splice(1, 1, 'リネンのふきん', 'ミニタオル');
  lines.push(`差し替え後: ${cart.join(' / ')}（${cart.length}点）`);

  const emptyCart: string[] = [];
  lines.push(`空のカートから pop: ${emptyCart.pop()}`);
  return lines.join('\n');
}

checkString(
  '問題2: 出力5行',
  solveQ2(),
  '1点目を追加: 要素数1\n' +
    '追加後: ラベンダーの石けん / ハンドクリーム / マグカップ（3点）\n' +
    '取り消した商品: マグカップ（残り2点）\n' +
    '差し替え後: ラベンダーの石けん / リネンのふきん / ミニタオル（3点）\n' +
    '空のカートから pop: undefined'
);

// 問題2の別解（slice + concat で新しいカートを作る）
function solveQ2Alternative(): string {
  const cart: string[] = ['ラベンダーの石けん', 'ハンドクリーム'];

  const before = cart.slice(0, 1);
  const after = cart.slice(2);
  const nextCart = before.concat(['リネンのふきん', 'ミニタオル']).concat(after);

  return `${nextCart.join(' / ')} / 元は${cart.length}点`;
}

checkString(
  '問題2 別解: 元の配列を書き換えない',
  solveQ2Alternative(),
  'ラベンダーの石けん / リネンのふきん / ミニタオル / 元は2点'
);

// ---------------------------------------------------------------------------
// 問題3：元の配列を壊さずに加工する
// ---------------------------------------------------------------------------
function solveQ3(): string {
  const allNames: string[] = [
    'ラベンダーの石けん',
    'ハンドクリーム',
    'マグカップ',
    'リネンのふきん',
  ];
  const newArrivals: string[] = ['アロマキャンドル', 'ギフトボックス'];

  const firstTwo = allNames.slice(0, 2);
  const lastTwo = allNames.slice(-2);
  const merged = allNames.concat(newArrivals);

  const mugIndex = allNames.indexOf('マグカップ');
  const bathSaltIndex = allNames.indexOf('入浴剤');
  const bathSaltLabel = allNames.includes('入浴剤') ? '取り扱いあり' : '取り扱いなし';

  const reversed = allNames.toReversed();

  const lines: string[] = [];
  lines.push(`最初の2件: ${firstTwo.join(' / ')}`);
  lines.push(`最後の2件: ${lastTwo.join(' / ')}`);
  lines.push(`新入荷を追加: ${merged.length}点（元の配列は${allNames.length}点）`);
  lines.push(`マグカップの位置: ${mugIndex}`);
  lines.push(`入浴剤の位置: ${bathSaltIndex}`);
  lines.push(`入浴剤: ${bathSaltLabel}`);
  lines.push(`逆順（新しい配列）: ${reversed.join(' / ')}`);
  lines.push(`元の配列: ${allNames.join(' / ')}`);
  return lines.join('\n');
}

checkString(
  '問題3: 出力8行',
  solveQ3(),
  '最初の2件: ラベンダーの石けん / ハンドクリーム\n' +
    '最後の2件: マグカップ / リネンのふきん\n' +
    '新入荷を追加: 6点（元の配列は4点）\n' +
    'マグカップの位置: 2\n' +
    '入浴剤の位置: -1\n' +
    '入浴剤: 取り扱いなし\n' +
    '逆順（新しい配列）: リネンのふきん / マグカップ / ハンドクリーム / ラベンダーの石けん\n' +
    '元の配列: ラベンダーの石けん / ハンドクリーム / マグカップ / リネンのふきん'
);

// slice(-2) と slice(2) は 4件の配列では同じ結果になる
const q3Names: string[] = ['a', 'b', 'c', 'd'];
checkString('問題3: slice(-2) と slice(2)', q3Names.slice(-2).join(','), q3Names.slice(2).join(','));

// ---------------------------------------------------------------------------
// 問題4：価格表を書き換えられないようにする
// ---------------------------------------------------------------------------
const MASTER_PRICES: readonly number[] = [480, 1800, 2350, 990];

function maxPrice(prices: readonly number[]): number {
  let max = 0;
  for (const price of prices) {
    if (price > max) {
      max = price;
    }
  }
  return max;
}

function solveQ4(): string {
  const lines: string[] = [];
  lines.push(`価格表: ${MASTER_PRICES.join(' / ')}`);
  lines.push(`件数: ${MASTER_PRICES.length}件`);
  lines.push(`最後の価格: ${MASTER_PRICES.at(-1) ?? 0}円`);
  lines.push(`最初の2件: ${MASTER_PRICES.slice(0, 2).join(' / ')}`);
  lines.push(`1800円の位置: ${MASTER_PRICES.indexOf(1800)}`);
  lines.push(`合計: ${sumPrices(MASTER_PRICES)}円`);
  lines.push(`最高値: ${maxPrice(MASTER_PRICES)}円`);
  return lines.join('\n');
}

checkString(
  '問題4: 出力7行',
  solveQ4(),
  '価格表: 480 / 1800 / 2350 / 990\n' +
    '件数: 4件\n' +
    '最後の価格: 990円\n' +
    '最初の2件: 480 / 1800\n' +
    '1800円の位置: 1\n' +
    '合計: 5620円\n' +
    '最高値: 2350円'
);

// 空の配列でも 0 を返す（境界の確認）
const q4Empty: readonly number[] = [];
checkNumber('問題4: 空の配列の合計', sumPrices(q4Empty), 0);
checkNumber('問題4: 空の配列の最高値', maxPrice(q4Empty), 0);

// 選択問題(B)の裏付け：const の配列は push できる
const q4MutablePrices: number[] = [480];
q4MutablePrices.push(1800);
checkNumber('問題4: 選択問題(B) の確認', q4MutablePrices.length, 2);

// ---------------------------------------------------------------------------
// 問題5：タプルで「決まった組」を表す
// ---------------------------------------------------------------------------
function solveQ5(): string {
  const boxSize: [width: number, height: number] = [24, 18];
  const nameAndPrice: readonly [string, number] = ['ハンドクリーム', 1800];

  const enough = checkStock(12, 2);
  const notEnough = checkStock(3, 5);
  const soldOut = checkStock(0, 1);
  const zeroQuantity = checkStock(12, 0);

  const lines: string[] = [];
  lines.push(
    `箱: 幅${boxSize[0]}cm × 高さ${boxSize[1]}cm / 面積${boxSize[0] * boxSize[1]}平方cm`
  );
  lines.push(`在庫12点に2点: ${enough[0]} / ${enough[1]}`);
  lines.push(`在庫3点に5点: ${notEnough[0]} / ${notEnough[1]}`);
  lines.push(`在庫0点に1点: ${soldOut[0]} / ${soldOut[1]}`);
  lines.push(`在庫12点に0点: ${zeroQuantity[0]} / ${zeroQuantity[1]}`);
  lines.push(`ペア: ${nameAndPrice[0]} ${nameAndPrice[1]}円`);
  return lines.join('\n');
}

checkString(
  '問題5: 出力6行',
  solveQ5(),
  '箱: 幅24cm × 高さ18cm / 面積432平方cm\n' +
    '在庫12点に2点: true / 2点を注文できます\n' +
    '在庫3点に5点: false / 在庫が3点しかありません\n' +
    '在庫0点に1点: false / 在庫切れです\n' +
    '在庫12点に0点: false / 数量を1点以上にしてください\n' +
    'ペア: ハンドクリーム 1800円'
);

// 判定の順序（数量を先に弾かないと「0点を注文できます」になる）
checkBoolean('問題5: 数量0は先に弾く', checkStock(12, 0)[0], false);
checkString('問題5: 在庫ちょうどは注文できる', checkStock(2, 2)[1], '2点を注文できます');

// ---------------------------------------------------------------------------
// 問題6：タプルの配列でカートの支払総額を出す
// ---------------------------------------------------------------------------
function solveQ6(): string {
  const cartLines: [name: string, unitPrice: number, quantity: number][] = [
    ['ラベンダーの石けん', 480, 2],
    ['ハンドクリーム', 1800, 1],
    ['リネンのふきん', 990, 3],
  ];

  const lines: string[] = [];
  for (const line of cartLines) {
    const lineTotal = line[1] * line[2];
    lines.push(`${line[0]} ${line[1]}円 × ${line[2]}点 = ${lineTotal}円`);
  }

  const subtotal = calcSubtotal(cartLines);
  lines.push(`明細${cartLines.length}件 / 小計${subtotal}円`);
  lines.push(`割引なし: お支払い${calcPayableAmount(subtotal, noDiscount)}円`);
  lines.push(`ブロンズ3%: お支払い${calcPayableAmount(subtotal, bronzeRule)}円`);
  lines.push(`ゴールド10%: お支払い${calcPayableAmount(subtotal, goldRule)}円`);
  return lines.join('\n');
}

checkString(
  '問題6: 出力7行',
  solveQ6(),
  'ラベンダーの石けん 480円 × 2点 = 960円\n' +
    'ハンドクリーム 1800円 × 1点 = 1800円\n' +
    'リネンのふきん 990円 × 3点 = 2970円\n' +
    '明細3件 / 小計5730円\n' +
    '割引なし: お支払い6303円\n' +
    'ブロンズ3%: お支払い6114円\n' +
    'ゴールド10%: お支払い5672円'
);

// 問題6の手順ごとの検算（解答の説明に書いた数値）
checkNumber('問題6: 小計', 480 * 2 + 1800 * 1 + 990 * 3, 5730);
checkNumber('問題6: ブロンズの割引額', bronzeRule(5730), 171);
checkNumber('問題6: ブロンズの消費税', Math.floor((5730 - 171) * TAX_RATE), 555);
checkNumber('問題6: ゴールドの割引額', goldRule(5730), 573);
checkNumber('問題6: ゴールドの消費税', Math.floor((5730 - 573) * TAX_RATE), 515);
checkNumber('問題6: 割引なしの消費税', Math.floor(5730 * TAX_RATE), 573);

// 割引額は小計を超えない（Math.min の上限）
// 小計200円に300円引きを適用しても割引額は200円で止まる。
// 割引後小計0円 → 消費税0円 → 税込商品合計0円 → 送料500円 → 支払総額500円。
checkNumber('問題6: 割引額の上限', calcPayableAmount(200, () => 300), 500);

// ---------------------------------------------------------------------------
// 問題7：カテゴリ別の在庫レポート
// ---------------------------------------------------------------------------
const q7Categories: readonly [name: string, products: readonly [string, number, number][]][] = [
  [
    'バス・ボディ',
    [
      ['ラベンダーの石けん', 480, 12],
      ['ハンドクリーム', 1800, 0],
    ],
  ],
  [
    'キッチン',
    [
      ['マグカップ', 2350, 3],
      ['リネンのふきん', 990, 8],
    ],
  ],
  ['ギフト', []],
];

function solveQ7(): string {
  const outOfStockNames: string[] = [];
  let totalProductCount = 0;
  let totalStockValue = 0;

  const lines: string[] = [];

  for (const category of q7Categories) {
    const categoryName = category[0];
    const products = category[1];

    let inStockCount = 0;
    let stockValue = 0;

    for (const product of products) {
      const stock = product[2];
      stockValue += product[1] * stock;

      if (stock <= 0) {
        outOfStockNames.push(product[0]);
        continue;
      }
      inStockCount += 1;
    }

    totalProductCount += products.length;
    totalStockValue += stockValue;

    if (products.length === 0) {
      lines.push(`[${categoryName}] 商品はまだありません`);
      continue;
    }

    const summary = `商品${products.length}点 / 在庫あり${inStockCount}点 / 在庫金額${stockValue}円`;
    lines.push(`[${categoryName}] ${summary}`);
  }

  lines.push(`全体: 商品${totalProductCount}点 / 在庫金額${totalStockValue}円`);
  lines.push(`在庫切れの商品: ${outOfStockNames.join(' / ')}`);
  return lines.join('\n');
}

const q7Expected =
  '[バス・ボディ] 商品2点 / 在庫あり1点 / 在庫金額5760円\n' +
  '[キッチン] 商品2点 / 在庫あり2点 / 在庫金額14970円\n' +
  '[ギフト] 商品はまだありません\n' +
  '全体: 商品4点 / 在庫金額20730円\n' +
  '在庫切れの商品: ハンドクリーム';

checkString('問題7: レポート5行', solveQ7(), q7Expected);

// 在庫金額の検算
checkNumber('問題7: バス・ボディの在庫金額', 480 * 12 + 1800 * 0, 5760);
checkNumber('問題7: キッチンの在庫金額', 2350 * 3 + 990 * 8, 14970);
checkNumber('問題7: 全体の在庫金額', 5760 + 14970, 20730);

// 問題7の別解：カテゴリ1件の集計を関数に切り出す
function summarizeCategory(
  products: readonly [string, number, number][]
): [count: number, inStockCount: number, stockValue: number, outOfStock: string[]] {
  let inStockCount = 0;
  let stockValue = 0;
  const outOfStock: string[] = [];

  for (const product of products) {
    stockValue += product[1] * product[2];
    if (product[2] <= 0) {
      outOfStock.push(product[0]);
      continue;
    }
    inStockCount += 1;
  }

  return [products.length, inStockCount, stockValue, outOfStock];
}

function solveQ7Alternative(): string {
  const outOfStockNames: string[] = [];
  let totalProductCount = 0;
  let totalStockValue = 0;

  const lines: string[] = [];

  for (const category of q7Categories) {
    const result = summarizeCategory(category[1]);

    totalProductCount += result[0];
    totalStockValue += result[2];
    for (const name of result[3]) {
      outOfStockNames.push(name);
    }

    if (result[0] === 0) {
      lines.push(`[${category[0]}] 商品はまだありません`);
      continue;
    }

    const summary = `商品${result[0]}点 / 在庫あり${result[1]}点 / 在庫金額${result[2]}円`;
    lines.push(`[${category[0]}] ${summary}`);
  }

  lines.push(`全体: 商品${totalProductCount}点 / 在庫金額${totalStockValue}円`);
  lines.push(`在庫切れの商品: ${outOfStockNames.join(' / ')}`);
  return lines.join('\n');
}

checkString('問題7 別解: 模範解答と同じ出力', solveQ7Alternative(), q7Expected);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session07: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session07: ok');
