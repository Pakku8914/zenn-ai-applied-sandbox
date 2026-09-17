/**
 * セッション9「値と参照・イミュータブル更新」のコード例と練習問題の解答を検証する。
 * 参照の共有によるバグは「再現した挙動」と「修正後の挙動」の両方を固定する。
 * 期待値と一致しなければエラー終了する。
 */

/** 比較できる値（=== の暗黙変換を避けるため、比較は常に !== で行う） */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}: 期待値 ${String(expected)} / 実際 ${String(actual)}`);
    process.exit(1);
  }
};

/** catch で受け取った値（unknown）からエラー名を取り出す */
const errorNameOf = (error: unknown): string => {
  if (error instanceof Error) {
    return error.name;
  }
  return '不明';
};

/** カートの1行 */
type CartLine = { name: string; price: number; quantity: number };

// 本書の共通ルール（requirements.md の共通シナリオで固定）
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;

/** 小計（税抜・整数円） */
const calcSubtotal = (lines: { price: number; quantity: number }[]): number => {
  let subtotal = 0;
  for (const line of lines) {
    subtotal += line.price * line.quantity;
  }
  return subtotal;
};

/** 送料の判定基準は「税込商品合計」 */
const calcShippingFee = (totalWithTax: number): number =>
  totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;

/** 支払総額（手順2〜7） */
const calcPayableAmount = (subtotal: number, rule: (subtotal: number) => number): number => {
  const discountAmount = Math.min(rule(subtotal), subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = Math.floor(discountedTotal * TAX_RATE);
  const totalWithTax = discountedTotal + tax;
  return totalWithTax + calcShippingFee(totalWithTax);
};

/** 表示用：マグカップ×1 ノート×2 のような文字列 */
const describeCart = (lines: { name: string; quantity: number }[]): string => {
  let text = '';
  for (const line of lines) {
    text += `${line.name}×${line.quantity} `;
  }
  return text.trim();
};

// ---------------------------------------------------------------------------
// 1. プリミティブとオブジェクト（本文「1. プリミティブとオブジェクト」/ src/session09/assign.ts）
// ---------------------------------------------------------------------------
const stockA = 30;
let stockB = stockA;
stockB = 25;
check('プリミティブは値が写る（元）', stockA, 30);
check('プリミティブは値が写る（先）', stockB, 25);

const priceListA = { mug: 1200 };
const priceListB = priceListA;
priceListB.mug = 1500;
check('オブジェクトは参照が写る（元）', priceListA.mug, 1500);
check('オブジェクトは参照が写る（先）', priceListB.mug, 1500);
check('同じオブジェクトを指している', priceListA === priceListB, true);

// const は中身を守らない
const constList = [1];
constList.push(2);
check('const の配列でも push できる', constList.length, 2);

// 文字列はイミュータブル（S02 の復習）
const productCode = 'mug-001';
const upperCode = productCode.toUpperCase();
check('文字列メソッドは元を変えない', productCode, 'mug-001');
check('文字列メソッドは新しい値を返す', upperCode, 'MUG-001');

// 引数もプリミティブなら値が写る
const addOne = (value: number): number => {
  let local = value;
  local += 1;
  return local;
};
const argStock = 30;
check('プリミティブ引数の戻り値', addOne(argStock), 31);
check('プリミティブ引数は呼び出し側に影響しない', argStock, 30);

// ---------------------------------------------------------------------------
// 2. バグを再現する（本文「2. バグを再現する」）
// ---------------------------------------------------------------------------

// 2.1 テンプレートから商品を作る（src/session09/template-bug.ts）
const brokenTemplate = { name: '新商品', price: 0, stock: 0, categoryId: 1 };
const brokenMug = brokenTemplate;
brokenMug.name = 'マグカップ';
brokenMug.price = 1200;
const brokenNote = brokenTemplate;
brokenNote.name = 'ノート';
brokenNote.price = 480;

check(
  'バグ再現：3つとも同じ名前になる',
  `mug=${brokenMug.name} / note=${brokenNote.name} / template=${brokenTemplate.name}`,
  'mug=ノート / note=ノート / template=ノート'
);
check('バグ再現：同じオブジェクトである', brokenMug === brokenNote, true);
check('バグ再現：テンプレートまで汚れる', brokenTemplate.price, 480);

// 修正版（スプレッドで新しいオブジェクトを作る）
const PRODUCT_TEMPLATE = { name: '新商品', price: 0, stock: 0, categoryId: 1 };
const fixedMug = { ...PRODUCT_TEMPLATE, name: 'マグカップ', price: 1200 };
const fixedNote = { ...PRODUCT_TEMPLATE, name: 'ノート', price: 480 };

check(
  '修正版：それぞれ独立している',
  `mug=${fixedMug.name} / note=${fixedNote.name} / template=${PRODUCT_TEMPLATE.name}`,
  'mug=マグカップ / note=ノート / template=新商品'
);
check('修正版：別のオブジェクトである', fixedMug === fixedNote, false);
check('修正版：テンプレートは無傷', PRODUCT_TEMPLATE.price, 0);
// なお `{ name: 'マグカップ', ...PRODUCT_TEMPLATE }` と順番を逆にすると、
// TypeScript が TS2783（この指定は上書きされます）で止めてくれるため、ここでは検証しない。

// 2.2 カートに同じオブジェクトを2回入れる（src/session09/cart-bug.ts）
const sharedMugLine = { name: 'マグカップ', price: 1200, quantity: 1 };
const brokenCart: CartLine[] = [sharedMugLine, sharedMugLine];
const brokenTarget = brokenCart[1];
if (brokenTarget !== undefined) {
  brokenTarget.quantity = 2;
}
let brokenCartText = '';
for (const line of brokenCart) {
  brokenCartText += `${line.name} × ${line.quantity} = ${line.price * line.quantity}円\n`;
}
check(
  'バグ再現：両方の行が2点になる',
  brokenCartText,
  'マグカップ × 2 = 2400円\nマグカップ × 2 = 2400円\n'
);
check('バグ再現：小計が 4800円になる', calcSubtotal(brokenCart), 4800);

// 修正版（2行目はコピーして作る）
const baseMugLine = { name: 'マグカップ', price: 1200, quantity: 1 };
const fixedCart: CartLine[] = [baseMugLine, { ...baseMugLine, quantity: 2 }];
check('修正版：小計は 3600円', calcSubtotal(fixedCart), 3600);
check('修正版：1行目は1点のまま', baseMugLine.quantity, 1);

// 2.3 関数に渡したオブジェクトを書き換える（bad-argument.ts / good-argument.ts）
const applyDiscountBad = (line: CartLine, percent: number): number => {
  line.price = line.price - Math.floor((line.price * percent) / 100);
  return line.price;
};
const badArgLine = { name: 'マグカップ', price: 1200, quantity: 1 };
check('Bad：戻り値は割引後の価格', applyDiscountBad(badArgLine, 5), 1140);
check('Bad：元のオブジェクトまで変わる', badArgLine.price, 1140);

const withDiscountedPrice = (line: CartLine, percent: number): CartLine => ({
  ...line,
  price: line.price - Math.floor((line.price * percent) / 100),
});
const goodArgLine = { name: 'マグカップ', price: 1200, quantity: 1 };
const discountedLine = withDiscountedPrice(goodArgLine, 5);
check('Good：新しい行の価格', discountedLine.price, 1140);
check('Good：元の行は無傷', goodArgLine.price, 1200);

// 仮引数に別のオブジェクトを代入しても呼び出し側は変わらない
const replaceLine = (line: CartLine): CartLine => {
  let local = line;
  local = { ...line, price: 0 };
  return local;
};
const keptLine = { name: 'マグカップ', price: 1200, quantity: 1 };
check('仮引数への代入は呼び出し側に影響しない', replaceLine(keptLine).price, 0);
check('呼び出し側の価格はそのまま', keptLine.price, 1200);

// ---------------------------------------------------------------------------
// 3. 浅いコピーと深いコピー（本文「3. 浅いコピーと深いコピー」）
// ---------------------------------------------------------------------------

// 3.1 プリミティブだけなら浅いコピーで安全（src/session09/shallow.ts）
const shallowOriginalProduct = { name: 'マグカップ', price: 1200, stock: 30 };
const shallowCopiedProduct = { ...shallowOriginalProduct };
shallowCopiedProduct.stock = 25;
check('浅いコピー：元は無傷', shallowOriginalProduct.stock, 30);
check('浅いコピー：コピー側だけ変わる', shallowCopiedProduct.stock, 25);
check('浅いコピー：別のオブジェクト', shallowOriginalProduct === shallowCopiedProduct, false);

// 3.2 ネストは共有される（src/session09/shallow-trap.ts）
const trapCampaign = {
  title: '夏の雑貨フェア',
  discountPercent: 5,
  targets: ['マグカップ', 'ノート'],
};
const trapCopy = { ...trapCampaign };
trapCopy.title = '秋の雑貨フェア';
trapCopy.targets.push('トートバッグ');
check('浅いコピー：文字列は独立する（元）', trapCampaign.title, '夏の雑貨フェア');
check('浅いコピー：文字列は独立する（先）', trapCopy.title, '秋の雑貨フェア');
check('バグ再現：ネストした配列は共有される', trapCampaign.targets.length, 3);
check('バグ再現：3件目の中身', `${trapCampaign.targets[2]}`, 'トートバッグ');
check('浅いコピー：配列は同じ参照', trapCampaign.targets === trapCopy.targets, true);

// 3.3 深いコピー（src/session09/deep.ts）
const deepCampaign = {
  title: '夏の雑貨フェア',
  discountPercent: 5,
  targets: ['マグカップ', 'ノート'],
};
const deepCloned = structuredClone(deepCampaign);
deepCloned.targets.push('トートバッグ');
check('深いコピー：元の targets は2件', deepCampaign.targets.length, 2);
check('深いコピー：コピーの targets は3件', deepCloned.targets.length, 3);
check('深いコピー：配列は別物', deepCampaign.targets === deepCloned.targets, false);

// 3.4 structuredClone の制約（src/session09/clone-error.ts）
const productWithMethod = {
  name: 'マグカップ',
  format: (price: number): string => `${price}円`,
};
let cloneErrorName = 'エラーなし';
try {
  structuredClone(productWithMethod);
} catch (error) {
  cloneErrorName = errorNameOf(error);
}
check('関数を含むと DataCloneError になる', cloneErrorName, 'DataCloneError');

// 3.5 JSON 往復は値を壊す（bad-json-copy.ts / good-structured-clone.ts）
const snapshot = {
  name: 'マグカップ',
  checkedAt: new Date('2026-08-27T00:00:00.000Z'),
  memo: undefined,
  averageDays: NaN,
};
const jsonSnapshot = JSON.parse(JSON.stringify(snapshot)) as {
  name: string;
  checkedAt: unknown;
  averageDays: unknown;
  memo?: unknown;
};
check('Bad：Date が文字列になる', typeof jsonSnapshot.checkedAt, 'string');
check('Bad：undefined のキーは消える', 'memo' in jsonSnapshot, false);
check('Bad：NaN は null になる', jsonSnapshot.averageDays === null, true);

const clonedSnapshot = structuredClone(snapshot);
check('Good：Date のまま', clonedSnapshot.checkedAt instanceof Date, true);
check('Good：undefined のキーも残る', 'memo' in clonedSnapshot, true);
check('Good：NaN のまま', Number.isNaN(clonedSnapshot.averageDays), true);

// ---------------------------------------------------------------------------
// 4. イミュータブルに更新する（本文「4. イミュータブルに更新する」）
// ---------------------------------------------------------------------------

// 4.1 オブジェクトの1プロパティ（src/session09/immutable-object.ts）
const immutableMugLine = { name: 'マグカップ', price: 1200, quantity: 1 };
const immutableUpdatedLine = { ...immutableMugLine, quantity: 3 };
check('元の数量', immutableMugLine.quantity, 1);
check('新しい行の数量', immutableUpdatedLine.quantity, 3);
check('別のオブジェクト', immutableMugLine === immutableUpdatedLine, false);

// 4.2 配列の追加・削除（src/session09/immutable-array.ts）
const arrayCart: CartLine[] = [
  { name: 'マグカップ', price: 1200, quantity: 1 },
  { name: 'ノート', price: 480, quantity: 2 },
];
const arrayAdded = [...arrayCart, { name: 'ボールペン', price: 250, quantity: 1 }];
const removeAt = (lines: CartLine[], index: number): CartLine[] => [
  ...lines.slice(0, index),
  ...lines.slice(index + 1),
];
const arrayRemoved = removeAt(arrayAdded, 1);
check('元　', `元　：${describeCart(arrayCart)}`, '元　：マグカップ×1 ノート×2');
check('追加', `追加：${describeCart(arrayAdded)}`, '追加：マグカップ×1 ノート×2 ボールペン×1');
check('削除', `削除：${describeCart(arrayRemoved)}`, '削除：マグカップ×1 ボールペン×1');
check('元の配列の件数は変わらない', arrayCart.length, 2);

// 4.3 map で1件だけ差し替える（src/session09/immutable-replace.ts）
const replaceCart: CartLine[] = [
  { name: 'マグカップ', price: 1200, quantity: 1 },
  { name: 'ノート', price: 480, quantity: 2 },
];
const replacedCart = replaceCart.map((line) =>
  line.name === 'マグカップ' ? { ...line, quantity: 3 } : line
);
check('map：元の小計', calcSubtotal(replaceCart), 2160);
check('map：新しい小計', calcSubtotal(replacedCart), 4560);
check('map：配列は別物', replaceCart === replacedCart, false);
check('map：差し替えなかった行は共有される', replaceCart[1] === replacedCart[1], true);

// 4.4 ネストの更新（src/session09/immutable-nested.ts）
const nestedOrder = {
  id: 'A-1001',
  shipping: { fee: 500, area: '東京都' },
  items: [{ name: 'マグカップ', price: 1200, quantity: 1 }],
};
const freeShippingOrder = {
  ...nestedOrder,
  shipping: { ...nestedOrder.shipping, fee: 0 },
};
check('ネスト更新：元の送料', nestedOrder.shipping.fee, 500);
check('ネスト更新：新しい送料', freeShippingOrder.shipping.fee, 0);
check('ネスト更新：shipping は別物', nestedOrder.shipping === freeShippingOrder.shipping, false);
check('ネスト更新：items は共有される', nestedOrder.items === freeShippingOrder.items, true);

// Bad/Good（bad-update.ts / good-update.ts）
const setQuantityBad = (lines: CartLine[], name: string, quantity: number): void => {
  for (const line of lines) {
    if (line.name === name) {
      line.quantity = quantity;
    }
  }
};
const badUpdateCart: CartLine[] = [{ name: 'マグカップ', price: 1200, quantity: 1 }];
setQuantityBad(badUpdateCart, 'マグカップ', 3);
check('Bad：呼び出し側のカートが変わる', calcSubtotal(badUpdateCart), 3600);

const withQuantity = (lines: CartLine[], name: string, quantity: number): CartLine[] =>
  lines.map((line) => (line.name === name ? { ...line, quantity } : line));
const goodUpdateCart: CartLine[] = [{ name: 'マグカップ', price: 1200, quantity: 1 }];
const goodUpdatedCart = withQuantity(goodUpdateCart, 'マグカップ', 3);
check('Good：元のカートは無傷', calcSubtotal(goodUpdateCart), 1200);
check('Good：新しいカートの小計', calcSubtotal(goodUpdatedCart), 3600);
check('Good：参照の比較で変化を検出できる', goodUpdateCart === goodUpdatedCart, false);

// ---------------------------------------------------------------------------
// 5. as const と Object.freeze（本文「5. 読み取り専用を宣言する」）
// ---------------------------------------------------------------------------
const SHIPPING_LABELS = ['通常配送', '速達'] as const;
const labelCountBeforePush: number = SHIPPING_LABELS.length; // 型はリテラル型 2
const pushLabel = (labels: string[], label: string): void => {
  labels.push(label);
};
pushLabel(SHIPPING_LABELS as unknown as string[], '翌日配送');
check('as const：型の上の件数', labelCountBeforePush, 2);
check('as const：実行時には守られない', SHIPPING_LABELS.length, 3);

const SHOP_CONFIG = Object.freeze({
  name: 'ミニ雑貨ショップ',
  shippingFee: 500,
  campaignTargets: ['マグカップ', 'ノート'],
});
check('Object.freeze で凍結されている', Object.isFrozen(SHOP_CONFIG), true);

const forceUpdate = (target: { shippingFee: number }, fee: number): string => {
  try {
    target.shippingFee = fee;
    return '書き換えに成功しました';
  } catch (error) {
    return `書き換えは拒否されました（${errorNameOf(error)}）`;
  }
};
check(
  'freeze：実行時に代入が拒否される',
  forceUpdate(SHOP_CONFIG, 0),
  '書き換えは拒否されました（TypeError）'
);
check('freeze：値は変わらない', SHOP_CONFIG.shippingFee, 500);

SHOP_CONFIG.campaignTargets.push('トートバッグ');
check('freeze は浅い（ネストは凍結されない）', SHOP_CONFIG.campaignTargets.length, 3);

// 凍結した配列に push すると TypeError になる
const FROZEN_LABELS = Object.freeze(['通常配送', '速達']);
const pushToFrozen = (labels: string[], label: string): string => {
  try {
    labels.push(label);
    return '追加できました';
  } catch (error) {
    return errorNameOf(error);
  }
};
check(
  '凍結した配列への push は TypeError',
  pushToFrozen(FROZEN_LABELS as unknown as string[], '翌日配送'),
  'TypeError'
);
check('凍結した配列の件数は変わらない', FROZEN_LABELS.length, 2);

// ---------------------------------------------------------------------------
// 6. 等価比較は参照の比較（本文「6. 等価比較は参照の比較」）
// ---------------------------------------------------------------------------
const eqLineA = { name: 'マグカップ', price: 1200, quantity: 1 };
const eqLineB = { name: 'マグカップ', price: 1200, quantity: 1 };
const eqLineC = eqLineA;
check('中身が同じでも別のオブジェクト', eqLineA === eqLineB, false);
check('同じオブジェクトを指している', eqLineA === eqLineC, true);
check('プロパティはプリミティブなので値で比較される', eqLineA.name === eqLineB.name, true);

const isSameLine = (a: CartLine, b: CartLine): boolean =>
  a.name === b.name && a.price === b.price && a.quantity === b.quantity;
check('フィールドを比べる関数', isSameLine(eqLineA, eqLineB), true);

const jsonLineX = { name: 'マグカップ', price: 1200 };
const jsonLineY = { price: 1200, name: 'マグカップ' };
check(
  'Bad：JSON.stringify 比較はキー順で壊れる',
  JSON.stringify(jsonLineX) === JSON.stringify(jsonLineY),
  false
);
check(
  'キー順が同じなら true になる（動いているように見える）',
  JSON.stringify(jsonLineX) === JSON.stringify({ name: 'マグカップ', price: 1200 }),
  true
);

const indexOfCart: CartLine[] = [eqLineA];
const copiedForIndexOf = { ...eqLineA };
check('indexOf は参照で探す（同じ参照）', indexOfCart.indexOf(eqLineA), 0);
check('indexOf は参照で探す（コピー）', indexOfCart.indexOf(copiedForIndexOf), -1);

// ---------------------------------------------------------------------------
// 7. 練習問題の解答（解答章の「期待される出力」と一致すること）
// ---------------------------------------------------------------------------

// 問題1：代入で何が写るのか
const q1Stock = 30;
let q1CopiedStock = q1Stock;
q1CopiedStock = 25;
const q1Product = { name: 'マグカップ', price: 1200, stock: 30 };
const q1CopiedProduct = q1Product;
q1CopiedProduct.stock = 25;
check('問題1の1行目', `stock=${q1Stock} / copiedStock=${q1CopiedStock}`, 'stock=30 / copiedStock=25');
check(
  '問題1の2行目',
  `product.stock=${q1Product.stock} / copiedProduct.stock=${q1CopiedProduct.stock}`,
  'product.stock=25 / copiedProduct.stock=25'
);
check(
  '問題1の3行目',
  `product === copiedProduct: ${q1Product === q1CopiedProduct}`,
  'product === copiedProduct: true'
);

// 問題2：参照の共有バグを再現して直す（上で検証済みの内容を出力行として確認する）
check(
  '問題2の1行目',
  `【バグ版】mug=${brokenMug.name} / note=${brokenNote.name} / template=${brokenTemplate.name}` +
    `（同じオブジェクト: ${brokenMug === brokenNote}）`,
  '【バグ版】mug=ノート / note=ノート / template=ノート（同じオブジェクト: true）'
);
check(
  '問題2の2行目',
  `【修正版】mug=${fixedMug.name} / note=${fixedNote.name} / template=${PRODUCT_TEMPLATE.name}` +
    `（同じオブジェクト: ${fixedMug === fixedNote}）`,
  '【修正版】mug=マグカップ / note=ノート / template=新商品（同じオブジェクト: false）'
);

// 問題3：浅いコピーと深いコピーを比べる
const createCampaign = (): {
  title: string;
  discountPercent: number;
  targets: string[];
  startedAt: Date;
} => ({
  title: '夏の雑貨フェア',
  discountPercent: 5,
  targets: ['マグカップ', 'ノート'],
  startedAt: new Date('2026-08-01T00:00:00.000Z'),
});

const q3ShallowOriginal = createCampaign();
const q3ShallowCopy = { ...q3ShallowOriginal };
q3ShallowCopy.targets.push('トートバッグ');
check(
  '問題3の1行目',
  `浅いコピー：元の targets は ${q3ShallowOriginal.targets.length} 件（共有されている）`,
  '浅いコピー：元の targets は 3 件（共有されている）'
);

const q3JsonOriginal = createCampaign();
const q3JsonCopy = JSON.parse(JSON.stringify(q3JsonOriginal)) as {
  title: string;
  discountPercent: number;
  targets: string[];
  startedAt: unknown;
};
q3JsonCopy.targets.push('トートバッグ');
check(
  '問題3の2行目',
  `JSON往復：元の targets は ${q3JsonOriginal.targets.length} 件 / ` +
    `startedAt の型は ${typeof q3JsonCopy.startedAt}`,
  'JSON往復：元の targets は 2 件 / startedAt の型は string'
);

const q3DeepOriginal = createCampaign();
const q3DeepCopy = structuredClone(q3DeepOriginal);
q3DeepCopy.targets.push('トートバッグ');
check(
  '問題3の3行目',
  `深いコピー：元の targets は ${q3DeepOriginal.targets.length} 件 / ` +
    `startedAt は Date（${q3DeepCopy.startedAt instanceof Date}）`,
  '深いコピー：元の targets は 2 件 / startedAt は Date（true）'
);

// 問題4：カートをイミュータブルに更新する
const changeQuantity = (lines: CartLine[], name: string, quantity: number): CartLine[] =>
  lines.map((line) => (line.name === name ? { ...line, quantity } : line));

const addLine = (lines: CartLine[], line: CartLine): CartLine[] => [...lines, line];

const findIndexByName = (lines: CartLine[], name: string): number => {
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line !== undefined && line.name === name) {
      return i;
    }
  }
  return -1;
};

const removeLine = (lines: CartLine[], name: string): CartLine[] => {
  const index = findIndexByName(lines, name);
  if (index === -1) {
    return [...lines];
  }
  return [...lines.slice(0, index), ...lines.slice(index + 1)];
};

const report = (label: string, lines: CartLine[]): string =>
  `${label}：${describeCart(lines)} / 小計 ${calcSubtotal(lines)}円`;

const q4Cart: CartLine[] = [
  { name: 'マグカップ', price: 1200, quantity: 1 },
  { name: 'ノート', price: 480, quantity: 2 },
];
const q4AfterChange = changeQuantity(q4Cart, 'マグカップ', 3);
const q4AfterAdd = addLine(q4AfterChange, { name: 'ボールペン', price: 250, quantity: 1 });
const q4AfterRemove = removeLine(q4AfterAdd, 'ノート');

check('問題4の1行目', report('元のカート', q4Cart), '元のカート：マグカップ×1 ノート×2 / 小計 2160円');
check(
  '問題4の2行目',
  report('数量変更後', q4AfterChange),
  '数量変更後：マグカップ×3 ノート×2 / 小計 4560円'
);
check(
  '問題4の3行目',
  report('追加後', q4AfterAdd),
  '追加後：マグカップ×3 ノート×2 ボールペン×1 / 小計 4810円'
);
check(
  '問題4の4行目',
  report('削除後', q4AfterRemove),
  '削除後：マグカップ×3 ボールペン×1 / 小計 3850円'
);
check(
  '問題4の5行目',
  report('元のカート（再確認）', q4Cart),
  '元のカート（再確認）：マグカップ×1 ノート×2 / 小計 2160円'
);
check('問題4：該当なしの削除は同じ内容の新しい配列', removeLine(q4Cart, 'タオル').length, 2);
check('問題4：該当なしでも別の配列', removeLine(q4Cart, 'タオル') === q4Cart, false);
check('問題4：添字が見つからないときは -1', findIndexByName(q4Cart, 'タオル'), -1);

// 問題4 別解：structuredClone で全件コピーしてから書き換える
const changeQuantityByClone = (
  lines: CartLine[],
  name: string,
  quantity: number
): CartLine[] => {
  const copied = structuredClone(lines);
  for (const line of copied) {
    if (line.name === name) {
      line.quantity = quantity;
    }
  }
  return copied;
};
const q4Cloned = changeQuantityByClone(q4Cart, 'マグカップ', 3);
check('問題4 別解：小計は模範解答と一致', calcSubtotal(q4Cloned), calcSubtotal(q4AfterChange));
check('問題4 別解：元のカートは無傷', calcSubtotal(q4Cart), 2160);
check('問題4 別解：変えていない行まで別物になる', q4Cloned[1] === q4Cart[1], false);

// 問題5：as const と Object.freeze
const RANK_LABELS = ['gold', 'silver', 'bronze', 'none'] as const;
const labelCountByType: number = RANK_LABELS.length;
const q5PushLabel = (labels: string[], label: string): void => {
  labels.push(label);
};
q5PushLabel(RANK_LABELS as unknown as string[], 'platinum');
check(
  '問題5の1行目',
  `as const の配列：型の上では ${labelCountByType} 件 / 実行時は ${RANK_LABELS.length} 件`,
  'as const の配列：型の上では 4 件 / 実行時は 5 件'
);

const Q5_SHOP_CONFIG = Object.freeze({
  name: 'ミニ雑貨ショップ',
  shippingFee: 500,
  campaignTargets: ['マグカップ', 'ノート'],
});
check(
  '問題5の2行目',
  `freeze したプロパティ：${forceUpdate(Q5_SHOP_CONFIG, 0)} → shippingFee = ${Q5_SHOP_CONFIG.shippingFee}`,
  'freeze したプロパティ：書き換えは拒否されました（TypeError） → shippingFee = 500'
);
Q5_SHOP_CONFIG.campaignTargets.push('トートバッグ');
check(
  '問題5の3行目',
  `freeze は浅い：campaignTargets は ${Q5_SHOP_CONFIG.campaignTargets.length} 件に増えてしまった`,
  'freeze は浅い：campaignTargets は 3 件に増えてしまった'
);

// 問題6：値が同じかどうかを判定する
const hasSameLine = (lines: CartLine[], target: CartLine): boolean => {
  for (const line of lines) {
    if (isSameLine(line, target)) {
      return true;
    }
  }
  return false;
};
const q6LineA = { name: 'マグカップ', price: 1200, quantity: 1 };
const q6LineB = { name: 'マグカップ', price: 1200, quantity: 1 };
const q6SameOrder = { name: 'マグカップ', price: 1200, quantity: 1 };
const q6DifferentOrder = { price: 1200, quantity: 1, name: 'マグカップ' };
const q6Cart: CartLine[] = [q6LineA, { name: 'ノート', price: 480, quantity: 2 }];
const q6CopiedLine = { ...q6LineA };

check('問題6の1行目', `lineA === lineB: ${q6LineA === q6LineB}`, 'lineA === lineB: false');
check(
  '問題6の2行目',
  `isSameLine(lineA, lineB): ${isSameLine(q6LineA, q6LineB)}`,
  'isSameLine(lineA, lineB): true'
);
check(
  '問題6の3行目',
  `JSON.stringify 比較（キー順が同じ）: ${JSON.stringify(q6LineA) === JSON.stringify(q6SameOrder)}`,
  'JSON.stringify 比較（キー順が同じ）: true'
);
check(
  '問題6の4行目',
  `JSON.stringify 比較（キー順が違う）: ${
    JSON.stringify(q6LineA) === JSON.stringify(q6DifferentOrder)
  }`,
  'JSON.stringify 比較（キー順が違う）: false'
);
check(
  '問題6の5行目',
  `cart.indexOf(copiedLine): ${q6Cart.indexOf(q6CopiedLine)}`,
  'cart.indexOf(copiedLine): -1'
);
check(
  '問題6の6行目',
  `hasSameLine(cart, copiedLine): ${hasSameLine(q6Cart, q6CopiedLine)}`,
  'hasSameLine(cart, copiedLine): true'
);

// 問題6 別解：識別子で比較する
const isSameProduct = (a: { productId: number }, b: { productId: number }): boolean =>
  a.productId === b.productId;
check('問題6 別解：識別子が同じ', isSameProduct({ productId: 1 }, { productId: 1 }), true);
check('問題6 別解：識別子が違う', isSameProduct({ productId: 1 }, { productId: 2 }), false);

// 問題7：注文スナップショットを守る
type OrderSnapshot = {
  id: string;
  items: CartLine[];
  subtotal: number;
  payableAmount: number;
};

const makePercentDiscount = (percent: number): ((subtotal: number) => number) => {
  return (subtotal: number): number => Math.floor((subtotal * percent) / 100);
};

const createOrderBroken = (
  cart: CartLine[],
  rule: (subtotal: number) => number
): OrderSnapshot => {
  const subtotal = calcSubtotal(cart);
  return {
    id: 'A-1001',
    items: cart, // ここが罠
    subtotal,
    payableAmount: calcPayableAmount(subtotal, rule),
  };
};

const createOrder = (cart: CartLine[], rule: (subtotal: number) => number): OrderSnapshot => {
  const subtotal = calcSubtotal(cart);
  return Object.freeze({
    id: 'A-1002',
    items: structuredClone(cart),
    subtotal,
    payableAmount: calcPayableAmount(subtotal, rule),
  });
};

const sneakyUpdate = (lines: { name: string; quantity: number }[]): void => {
  for (const line of lines) {
    if (line.name === 'マグカップ') {
      line.quantity = 5;
    }
  }
};

const tryOverwrite = (order: { payableAmount: number }, amount: number): string => {
  try {
    order.payableAmount = amount;
    return '書き換えに成功しました';
  } catch (error) {
    return `拒否されました（${errorNameOf(error)}）`;
  }
};

const q7Cart: CartLine[] = [
  { name: 'マグカップ', price: 1200, quantity: 2 },
  { name: 'ノート', price: 480, quantity: 1 },
];
const silverRule = makePercentDiscount(5);
const brokenOrder = createOrderBroken(q7Cart, silverRule);
const fixedOrder = createOrder(q7Cart, silverRule);

check(
  '問題7の1行目',
  `注文作成時：小計 ${fixedOrder.subtotal}円 / 支払総額 ${fixedOrder.payableAmount}円`,
  '注文作成時：小計 2880円 / 支払総額 3009円'
);

// 支払総額の計算手順を1ステップずつ確認する（小計2880・5%割引）
const q7Discount = Math.floor((2880 * 5) / 100);
const q7Discounted = 2880 - q7Discount;
const q7Tax = Math.floor(q7Discounted * TAX_RATE);
const q7TotalWithTax = q7Discounted + q7Tax;
check('問題7 手順2 割引額', q7Discount, 144);
check('問題7 手順3 割引後小計', q7Discounted, 2736);
check('問題7 手順4 消費税', q7Tax, 273);
check('問題7 手順5 税込商品合計', q7TotalWithTax, 3009);
check('問題7 手順6 送料', calcShippingFee(q7TotalWithTax), 0);
check('問題7 手順7 支払総額', q7TotalWithTax + calcShippingFee(q7TotalWithTax), 3009);

sneakyUpdate(q7Cart);
const q7BrokenSubtotal = calcSubtotal(brokenOrder.items);
const q7FixedSubtotal = calcSubtotal(fixedOrder.items);

check(
  '問題7の3行目',
  `バグ版の注文：小計 ${q7BrokenSubtotal}円 / ` +
    `再計算した支払総額 ${calcPayableAmount(q7BrokenSubtotal, silverRule)}円（作成時とズレた）`,
  'バグ版の注文：小計 6480円 / 再計算した支払総額 6771円（作成時とズレた）'
);
check(
  '問題7の4行目',
  `修正版の注文：小計 ${q7FixedSubtotal}円 / ` +
    `再計算した支払総額 ${calcPayableAmount(q7FixedSubtotal, silverRule)}円（作成時と同じ）`,
  '修正版の注文：小計 2880円 / 再計算した支払総額 3009円（作成時と同じ）'
);
check(
  '問題7の5行目',
  `凍結した注文の書き換え：${tryOverwrite(fixedOrder, 0)}`,
  '凍結した注文の書き換え：拒否されました（TypeError）'
);
check('問題7：バグ版の保存済み金額は変わらない', brokenOrder.payableAmount, 3009);
check('問題7：バグ版は明細だけが変わる（不整合）', brokenOrder.items === q7Cart, true);
check('問題7：修正版の明細はカートと別物', fixedOrder.items === q7Cart, false);
check('問題7：修正版の金額は守られている', fixedOrder.payableAmount, 3009);

// 問題7 別解：map + スプレッドで1階層だけコピーする
const createOrderByMap = (cart: CartLine[], rule: (subtotal: number) => number): OrderSnapshot => {
  const subtotal = calcSubtotal(cart);
  return Object.freeze({
    id: 'A-1003',
    items: cart.map((line) => ({ ...line })),
    subtotal,
    payableAmount: calcPayableAmount(subtotal, rule),
  });
};
const mapOrderCart: CartLine[] = [
  { name: 'マグカップ', price: 1200, quantity: 2 },
  { name: 'ノート', price: 480, quantity: 1 },
];
const mapOrder = createOrderByMap(mapOrderCart, silverRule);
sneakyUpdate(mapOrderCart);
check('問題7 別解：支払総額は模範解答と一致', mapOrder.payableAmount, 3009);
check('問題7 別解：明細も守られている', calcSubtotal(mapOrder.items), 2880);

console.log('session09: ok');
