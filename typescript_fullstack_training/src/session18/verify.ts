// セッション18「エラーハンドリングと型安全な失敗表現」の検証スクリプト。
//
// 本文（063）と練習問題の解答（065）に載せたコードと同じロジックを実行し、
// 章に書いた「期待される出力」と一致するかを確認する。
// 1つでも一致しなければ非0で終了する。
//
// console.log を1行ずつ出す章のコードは、この検証では
// 「出力行を \n でつないだ文字列」を返す関数として表現している。
//
// 実行: docker compose exec ts npx tsx src/session18/verify.ts

import { readFile } from 'node:fs/promises';
import { delay } from '../session17/async-tools';
import { fixturePath } from '../session17/fixtures-path';
import type { CatalogItem } from '../session17/catalog';
import {
  ConfigError,
  FixtureReadError,
  InvariantError,
  describeErrorChain,
  isSensitiveKey,
  maskSensitive,
  toError,
  toLogSafeError,
  toMessage,
} from './errors';
import { collectResults, err, ok, tryCatch, tryCatchAsync, unwrapOrThrow } from './result';
import type { Result } from './result';
import {
  MAX_CART_QUANTITY,
  addToCart,
  buildReservations,
  describeShopError,
  findCatalogItem,
  formatReservation,
  loadCatalogSafely,
  parseQuantity,
  reserveStock,
} from './shop';
import type { Reservation, ReservationRequest, ShopError } from './shop';

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label}\n--- 期待値 ---\n${expected}\n--- 実際 ---\n${actual}`);
    failedCount += 1;
  }
}

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
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
// 共通のヘルパー
// ---------------------------------------------------------------------------

/** fixtures をテキストで読む。失敗はカスタムエラーで包み、cause に原因を残す */
async function loadFixtureText(fileName: string): Promise<string> {
  try {
    return await readFile(fixturePath(fileName), 'utf-8');
  } catch (caught: unknown) {
    throw new FixtureReadError(fileName, { cause: caught });
  }
}

/** 「起きないはず」の場所で Result を例外に変える（境界の外向き変換） */
function mustFindItem(items: readonly CatalogItem[], productId: number): CatalogItem {
  return unwrapOrThrow(
    findCatalogItem(items, productId),
    (error) =>
      new InvariantError(`カタログに必ずあるはずの商品が見つかりません: ${describeShopError(error)}`)
  );
}

/** 成功・失敗をそろえて1行にする */
function report(result: Result<Reservation, ShopError>): string {
  return result.kind === 'ok'
    ? `OK: ${formatReservation(result.value)}`
    : `NG: ${describeShopError(result.error)}`;
}

const catalogResult = await loadCatalogSafely();

if (catalogResult.kind === 'error') {
  // 検証の前提が崩れているので、ここは例外で止める
  throw new Error(`カタログの読み込みに失敗しました: ${describeShopError(catalogResult.error)}`);
}

const catalog = catalogResult.value;
checkNumber('前提: カタログは5件', catalog.length, 5);

// ---------------------------------------------------------------------------
// 本文 1節：throw / try / catch / finally
// ---------------------------------------------------------------------------
function toPositiveInt(input: string): number {
  const value = Number(input);

  if (input.trim() === '' || !Number.isInteger(value) || value <= 0) {
    throw new Error(`1以上の整数を入力してください: ${input}`);
  }
  return value;
}

function bodyTryCatch(input: string): string[] {
  const lines: string[] = [`--- 入力: ${input} ---`];

  try {
    lines.push(`数量: ${toPositiveInt(input)}点`);
  } catch (caught: unknown) {
    lines.push(`失敗: ${caught instanceof Error ? caught.message : '不明なエラー'}`);
  } finally {
    lines.push('後片付け（finally はいつでも通る）');
  }
  return lines;
}

checkString(
  '本文1節: try / catch / finally の通り方',
  [...bodyTryCatch('3'), ...bodyTryCatch('abc')].join('\n'),
  '--- 入力: 3 ---\n' +
    '数量: 3点\n' +
    '後片付け（finally はいつでも通る）\n' +
    '--- 入力: abc ---\n' +
    '失敗: 1以上の整数を入力してください: abc\n' +
    '後片付け（finally はいつでも通る）'
);

// finally の落とし穴：finally の return は try の return と例外の両方を上書きする
function badFinally(): string {
  try {
    return 'try が返した値';
  } finally {
    return 'finally が返した値';
  }
}

function swallowError(): string {
  try {
    throw new Error('本当に起きたエラー');
  } finally {
    return 'finally が返した値';
  }
}

checkString('本文1節: finally の return が try の return を上書きする', badFinally(), 'finally が返した値');
checkString('本文1節: finally の return が例外を消してしまう', swallowError(), 'finally が返した値');

// 誰も受け止めなかった Promise の失敗は unhandledRejection として通知される
const unhandledMessages: string[] = [];
const onUnhandledRejection = (reason: unknown): void => {
  unhandledMessages.push(toMessage(reason));
};

process.on('unhandledRejection', onUnhandledRejection);

void (async (): Promise<void> => {
  throw new Error('誰も受け止めなかった失敗');
})();

await delay(30);
process.off('unhandledRejection', onUnhandledRejection);

checkString(
  '本文1節: 未処理の rejection が通知される',
  unhandledMessages.join(','),
  '誰も受け止めなかった失敗'
);

// ---------------------------------------------------------------------------
// 本文 2節：catch で受け取る値は unknown
// ---------------------------------------------------------------------------
function throwVarious(kind: 'error' | 'string' | 'object'): never {
  if (kind === 'error') {
    throw new Error('Error を投げた');
  }
  if (kind === 'string') {
    throw '文字列を投げた';
  }
  throw { code: 500 };
}

function goodCatchMessage(fn: () => void): string {
  try {
    fn();
    return '成功';
  } catch (caught: unknown) {
    return toMessage(caught);
  }
}

function badCatchMessage(fn: () => void): string {
  try {
    fn();
    return '成功';
  } catch (caught: any) {
    // Bad: any にすると、Error でない値が来たときに undefined が漏れる
    return `${caught.message}`;
  }
}

checkString(
  '本文2節: toMessage は Error 以外も安全に文字列化する',
  [
    goodCatchMessage(() => throwVarious('error')),
    goodCatchMessage(() => throwVarious('string')),
    goodCatchMessage(() => throwVarious('object')),
  ].join('\n'),
  'Error を投げた\n文字列を投げた\n[object Object]'
);

checkString(
  '本文2節: any で受けると undefined が漏れる',
  badCatchMessage(() => throwVarious('string')),
  'undefined'
);

checkString(
  '本文2節: toError は Error 以外を包み直す',
  toError('文字列を投げた').message,
  'Error ではない値が投げられました: 文字列を投げた'
);
checkBoolean('本文2節: toError は Error をそのまま返す', toError(new Error('x')).message === 'x', true);

// ---------------------------------------------------------------------------
// 本文 3節：カスタムエラークラスと cause
// ---------------------------------------------------------------------------
class NoNameError extends Error {}

const noName = new NoNameError('メッセージ');
checkString('本文3節: name を設定しないと Error のまま', noName.name, 'Error');
checkString('本文3節: constructor.name はクラス名になる', noName.constructor.name, 'NoNameError');

const configError = new ConfigError('PAYMENT_WEBHOOK_SECRET が設定されていません');
checkString('本文3節: name を上書きしたクラス', configError.name, 'ConfigError');
checkBoolean('本文3節: instanceof Error は true', configError instanceof Error, true);
checkBoolean('本文3節: instanceof で種類を見分けられる', configError instanceof ConfigError, true);

const lowLevelError = new Error('ENOENT: no such file or directory');
const wrappedError = new FixtureReadError('missing.json', { cause: lowLevelError });

checkString(
  '本文3節: cause をたどった原因の連鎖',
  describeErrorChain(wrappedError),
  'FixtureReadError: データの読み込みに失敗しました: missing.json <- ' +
    'Error: ENOENT: no such file or directory'
);
checkString('本文3節: cause を持つエラーの fileName', wrappedError.fileName, 'missing.json');

// 実際のファイル読み込みでも cause がつながる（パスは環境で変わるので含有だけ確認する）
const realFailure = await tryCatchAsync(() => loadFixtureText('missing.json'));
const realChain = realFailure.kind === 'error' ? describeErrorChain(realFailure.error) : '';

checkString(
  '本文3節: 実ファイルの失敗も連鎖の先頭は自分のエラー',
  realChain.split(' <- ')[0] ?? '(なし)',
  'FixtureReadError: データの読み込みに失敗しました: missing.json'
);
checkBoolean('本文3節: 連鎖に ENOENT が含まれる', realChain.includes('ENOENT'), true);

// ---------------------------------------------------------------------------
// 本文 5節：Result で失敗を型に載せる
// ---------------------------------------------------------------------------
checkString(
  '本文5節: addToCart の成功と失敗',
  [
    report(addToCart(catalog, 3, '2')),
    report(addToCart(catalog, 3, '5')),
    report(addToCart(catalog, 99, '2')),
    report(addToCart(catalog, 3, 'abc')),
    report(addToCart(catalog, 3, '20')),
  ].join('\n'),
  'OK: マグカップ × 2点 = 4700円\n' +
    'NG: マグカップの在庫が足りません（希望 5点 / 在庫 3点）\n' +
    'NG: 商品が見つかりません（productId: 99）\n' +
    'NG: 数量は整数で入力してください（受け取った値: abc）\n' +
    'NG: 数量は1以上10以下で指定してください（受け取った値: 20）'
);

checkNumber('本文5節: 数量の上限は10', MAX_CART_QUANTITY, 10);

// 小さな関数を単体で使う（早期 return でつなぐ前の確認）
const mug = mustFindItem(catalog, 3);
const parsedQuantity = parseQuantity('2');

checkString(
  '本文5節: 部品を単体で使う',
  [
    parsedQuantity.kind === 'ok'
      ? `parseQuantity: ${parsedQuantity.value}`
      : `parseQuantity: ${describeShopError(parsedQuantity.error)}`,
    `reserveStock: ${report(reserveStock(mug, 2))}`,
    `reserveStock（在庫超過）: ${report(reserveStock(mug, 9))}`,
  ].join('\n'),
  'parseQuantity: 2\n' +
    'reserveStock: OK: マグカップ × 2点 = 4700円\n' +
    'reserveStock（在庫超過）: NG: マグカップの在庫が足りません（希望 9点 / 在庫 3点）'
);

// ---------------------------------------------------------------------------
// 本文 6節：境界で例外と Result を変換する
// ---------------------------------------------------------------------------
function parseJson(text: string): Result<unknown, Error> {
  return tryCatch<unknown>(() => JSON.parse(text));
}

function reportJson(text: string): string {
  const result = parseJson(text);
  return result.kind === 'ok' ? `${text} → 成功` : `${text} → 失敗（${result.error.name}）`;
}

checkString(
  '本文6節: tryCatch で JSON の失敗を値にする',
  [reportJson('{ "id": 1 }'), reportJson('not json')].join('\n'),
  '{ "id": 1 } → 成功\nnot json → 失敗（SyntaxError）'
);

const brokenLoader = (): Promise<CatalogItem[]> => {
  throw new FixtureReadError('products.json', { cause: lowLevelError });
};

const brokenCatalog = await loadCatalogSafely(brokenLoader);
const firstItem = catalog[0];

checkString(
  '本文6節: 読み込み失敗を Result に変える',
  [
    `カタログ: ${catalog.length}件（先頭 = ${firstItem === undefined ? '(なし)' : firstItem.name}）`,
    brokenCatalog.kind === 'ok'
      ? 'カタログ: 成功'
      : `NG: ${describeShopError(brokenCatalog.error)}`,
  ].join('\n'),
  'カタログ: 5件（先頭 = ラベンダーの石けん）\n' +
    'NG: 商品カタログを読み込めませんでした（データの読み込みに失敗しました: products.json）'
);

let invariantMessage = '(投げられませんでした)';
try {
  mustFindItem(catalog, 99);
} catch (caught: unknown) {
  invariantMessage = `${toError(caught).name}: ${toMessage(caught)}`;
}

checkString(
  '本文6節: unwrapOrThrow は境界で例外に変える',
  invariantMessage,
  'InvariantError: カタログに必ずあるはずの商品が見つかりません: 商品が見つかりません（productId: 99）'
);

// ---------------------------------------------------------------------------
// 本文 7節：エラー境界で失敗を集約する
// ---------------------------------------------------------------------------
function reportReservations(result: Result<Reservation[], ShopError[]>): string[] {
  if (result.kind === 'ok') {
    const total = result.value.reduce((sum, item) => sum + item.lineTotal, 0);
    return [`OK: ${result.value.length}件 / 合計 ${total}円`];
  }

  return [
    `NG: 失敗${result.error.length}件`,
    ...result.error.map((error) => `  - ${describeShopError(error)}`),
  ];
}

const successRequests: ReservationRequest[] = [
  { productId: 1, quantityInput: '2' },
  { productId: 3, quantityInput: '1' },
];
const failureRequests: ReservationRequest[] = [
  { productId: 1, quantityInput: '2' },
  { productId: 4, quantityInput: '1' },
  { productId: 99, quantityInput: '1' },
];

checkString(
  '本文7節: 失敗を集約したエラー境界',
  [
    '--- 成功するリクエスト ---',
    ...reportReservations(await buildReservations(successRequests)),
    '--- 失敗を含むリクエスト ---',
    ...reportReservations(await buildReservations(failureRequests)),
    '--- カタログが読めない場合 ---',
    ...reportReservations(await buildReservations(successRequests, brokenLoader)),
  ].join('\n'),
  '--- 成功するリクエスト ---\n' +
    'OK: 2件 / 合計 3310円\n' +
    '--- 失敗を含むリクエスト ---\n' +
    'NG: 失敗2件\n' +
    '  - リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点）\n' +
    '  - 商品が見つかりません（productId: 99）\n' +
    '--- カタログが読めない場合 ---\n' +
    'NG: 失敗1件\n' +
    '  - 商品カタログを読み込めませんでした（データの読み込みに失敗しました: products.json）'
);

// collectResults は「全部成功」と「失敗だけを集める」を切り替える
const collected = collectResults([addToCart(catalog, 1, '2'), addToCart(catalog, 3, '1')]);
checkBoolean('本文7節: 全部成功なら ok', collected.kind === 'ok', true);

// ---------------------------------------------------------------------------
// 本文 8節：ログに残してよい情報
// ---------------------------------------------------------------------------
const requestBody: Record<string, unknown> = {
  email: 'taro@example.com',
  password: 'hunter2',
  sessionId: 'a1b2c3',
  quantity: 2,
};

checkString(
  '本文8節: 機密のキーを伏せる',
  JSON.stringify(maskSensitive(requestBody)),
  '{"email":"taro@example.com","password":"[REDACTED]","sessionId":"[REDACTED]","quantity":2}'
);

checkBoolean('本文8節: passwordHash も機密と判定される', isSensitiveKey('passwordHash'), true);
checkBoolean('本文8節: quantity は機密ではない', isSensitiveKey('quantity'), false);

checkString(
  '本文8節: ログに出してよい部分だけを取り出す',
  JSON.stringify(toLogSafeError(wrappedError)),
  '{"name":"FixtureReadError",' +
    '"message":"データの読み込みに失敗しました: missing.json",' +
    '"chain":"FixtureReadError: データの読み込みに失敗しました: missing.json <- ' +
    'Error: ENOENT: no such file or directory"}'
);

// JSON.stringify(error) はメッセージを落とす（Error の message は列挙されない）
checkString('本文8節: JSON.stringify(new Error) は空オブジェクト', JSON.stringify(new Error('メッセージ')), '{}');

// ---------------------------------------------------------------------------
// 問題1：try / catch / finally と catch の絞り込み
// ---------------------------------------------------------------------------
function solveQ1ToQuantity(input: string): number {
  const value = Number(input);

  if (input.trim() === '' || !Number.isInteger(value)) {
    throw new Error(`数量は整数で入力してください: ${input}`);
  }
  if (value < 1 || value > MAX_CART_QUANTITY) {
    throw new Error(`数量は1以上${MAX_CART_QUANTITY}以下で指定してください: ${value}`);
  }
  return value;
}

function solveQ1Run(input: string): string[] {
  const lines: string[] = [`--- 入力: ${input} ---`];

  try {
    lines.push(`数量: ${solveQ1ToQuantity(input)}点`);
  } catch (caught: unknown) {
    lines.push(`失敗: ${toMessage(caught)}`);
  } finally {
    lines.push('処理を終了します');
  }
  return lines;
}

checkString(
  '問題1: 出力9行',
  [...solveQ1Run('3'), ...solveQ1Run('abc'), ...solveQ1Run('0')].join('\n'),
  '--- 入力: 3 ---\n' +
    '数量: 3点\n' +
    '処理を終了します\n' +
    '--- 入力: abc ---\n' +
    '失敗: 数量は整数で入力してください: abc\n' +
    '処理を終了します\n' +
    '--- 入力: 0 ---\n' +
    '失敗: 数量は1以上10以下で指定してください: 0\n' +
    '処理を終了します'
);

// ---------------------------------------------------------------------------
// 問題2：カスタムエラークラスと cause
// ---------------------------------------------------------------------------
class QuantityError extends Error {
  override readonly name = 'QuantityError';
  readonly input: string;

  constructor(input: string, options?: ErrorOptions) {
    super(`数量が不正です: ${input}`, options);
    this.input = input;
  }
}

class CheckoutError extends Error {
  override readonly name = 'CheckoutError';

  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
  }
}

function parseQuantityOrThrow(input: string): number {
  const value = Number(input);

  if (input.trim() === '' || !Number.isInteger(value) || value < 1 || value > MAX_CART_QUANTITY) {
    throw new QuantityError(input);
  }
  return value;
}

function checkoutQuantity(input: string): number {
  try {
    return parseQuantityOrThrow(input);
  } catch (caught: unknown) {
    throw new CheckoutError('注文を確定できませんでした', { cause: caught });
  }
}

/** cause をたどって、元になった QuantityError を探す */
function findQuantityError(value: unknown): QuantityError | undefined {
  let current: unknown = value;

  for (let depth = 0; depth < 5; depth += 1) {
    if (current instanceof QuantityError) {
      return current;
    }
    if (!(current instanceof Error)) {
      return undefined;
    }
    current = current.cause;
  }
  return undefined;
}

function solveQ2(): string {
  const lines: string[] = [];
  const direct = new QuantityError('abc');

  lines.push(`${direct.name}: ${direct.message}`);
  lines.push(`name = ${direct.name} / instanceof Error = ${direct instanceof Error}`);

  try {
    checkoutQuantity('abc');
    lines.push('成功してしまいました');
  } catch (caught: unknown) {
    lines.push(`連鎖: ${describeErrorChain(caught)}`);
    const original = findQuantityError(caught);
    lines.push(`入力の値: ${original === undefined ? '(不明)' : original.input}`);
  }
  return lines.join('\n');
}

checkString(
  '問題2: 出力4行',
  solveQ2(),
  'QuantityError: 数量が不正です: abc\n' +
    'name = QuantityError / instanceof Error = true\n' +
    '連鎖: CheckoutError: 注文を確定できませんでした <- QuantityError: 数量が不正です: abc\n' +
    '入力の値: abc'
);

// ---------------------------------------------------------------------------
// 問題3：投げるか返すかを書き分ける
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;

/** 設定不備は呼び出し側にできることが無い → throw */
function requireTaxRate(config: Record<string, unknown>): number {
  const value = config['taxRate'];

  if (typeof value !== 'number' || value < 0 || value > 1) {
    throw new ConfigError(`taxRate の設定が不正です: ${String(value)}`);
  }
  return value;
}

/** 入力の不正は呼び出し側が直せる → Result */
function parseAmount(input: string): Result<number, string> {
  const value = Number(input);

  if (input.trim() === '' || !Number.isInteger(value) || value < 0) {
    return err(`金額は0以上の整数で入力してください（受け取った値: ${input}）`);
  }
  return ok(value);
}

function estimateTotal(config: Record<string, unknown>, input: string): Result<number, string> {
  const rate = requireTaxRate(config);
  const amount = parseAmount(input);

  if (amount.kind === 'error') {
    return amount;
  }
  return ok(amount.value + Math.floor(amount.value * rate));
}

function solveQ3(): string {
  const config: Record<string, unknown> = { taxRate: TAX_RATE };
  const lines: string[] = [];

  const okResult = estimateTotal(config, '1000');
  lines.push(
    okResult.kind === 'ok' ? `1000 → 税込 ${okResult.value}円` : `1000 → 失敗: ${okResult.error}`
  );

  const ngResult = estimateTotal(config, 'abc');
  lines.push(
    ngResult.kind === 'ok' ? `abc → 税込 ${ngResult.value}円` : `abc → 失敗: ${ngResult.error}`
  );

  try {
    estimateTotal({}, '1000');
    lines.push('設定が壊れていても成功しました');
  } catch (caught: unknown) {
    const name = caught instanceof ConfigError ? caught.name : '想定外';
    lines.push(`設定が壊れている場合: ${name}: ${toMessage(caught)}`);
  }
  return lines.join('\n');
}

checkString(
  '問題3: 出力3行',
  solveQ3(),
  '1000 → 税込 1100円\n' +
    'abc → 失敗: 金額は0以上の整数で入力してください（受け取った値: abc）\n' +
    '設定が壊れている場合: ConfigError: taxRate の設定が不正です: undefined'
);

// ---------------------------------------------------------------------------
// 問題4：失敗の種類を増やして網羅性を守る
// ---------------------------------------------------------------------------
type ShopErrorV2 = ShopError | { kind: 'cart_full'; currentLines: number };

const MAX_CART_LINES = 3;

function assertNeverV2(value: never): never {
  throw new Error(`未対応の失敗があります: ${JSON.stringify(value)}`);
}

function describeShopErrorV2(error: ShopErrorV2): string {
  switch (error.kind) {
    case 'cart_full':
      return `カートの明細が上限${MAX_CART_LINES}件に達しています`;
    case 'invalid_quantity':
    case 'quantity_out_of_range':
    case 'product_not_found':
    case 'out_of_stock':
    case 'catalog_unavailable':
      return describeShopError(error);
    default:
      return assertNeverV2(error);
  }
}

function addLine(
  items: readonly CatalogItem[],
  lines: readonly Reservation[],
  productId: number,
  quantityInput: string
): Result<Reservation[], ShopErrorV2> {
  if (lines.length >= MAX_CART_LINES) {
    const error: ShopErrorV2 = { kind: 'cart_full', currentLines: lines.length };
    return err(error);
  }

  const added = addToCart(items, productId, quantityInput);
  if (added.kind === 'error') {
    return added;
  }
  return ok([...lines, added.value]);
}

function solveQ4(): string {
  const outputs: string[] = [];
  let lines: Reservation[] = [];
  const requests: ReservationRequest[] = [
    { productId: 1, quantityInput: '2' },
    { productId: 3, quantityInput: '1' },
    { productId: 5, quantityInput: '1' },
    { productId: 2, quantityInput: '1' },
  ];

  for (const [index, request] of requests.entries()) {
    const result = addLine(catalog, lines, request.productId, request.quantityInput);

    if (result.kind === 'ok') {
      lines = result.value;
      outputs.push(`${index + 1}件目: OK（明細${lines.length}件）`);
    } else {
      outputs.push(`${index + 1}件目: NG（${describeShopErrorV2(result.error)}）`);
    }
  }

  const shortage = addLine(catalog, [], 4, '1');
  outputs.push(
    shortage.kind === 'ok' ? '在庫不足: OK' : `在庫不足: NG（${describeShopErrorV2(shortage.error)}）`
  );
  return outputs.join('\n');
}

checkString(
  '問題4: 出力5行',
  solveQ4(),
  '1件目: OK（明細1件）\n' +
    '2件目: OK（明細2件）\n' +
    '3件目: OK（明細3件）\n' +
    '4件目: NG（カートの明細が上限3件に達しています）\n' +
    '在庫不足: NG（リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点））'
);

// ---------------------------------------------------------------------------
// 問題5：境界で例外と Result を変換する
// ---------------------------------------------------------------------------
async function readJsonSafely(fileName: string): Promise<Result<unknown, ShopError>> {
  const result = await tryCatchAsync<unknown>(async () => {
    const text = await loadFixtureText(fileName);
    return JSON.parse(text);
  });

  if (result.kind === 'error') {
    const error: ShopError = { kind: 'catalog_unavailable', reason: result.error.message };
    return err(error);
  }
  return ok(result.value);
}

async function solveQ5(): Promise<string> {
  const lines: string[] = [];

  const okResult = await readJsonSafely('products.json');
  const count = okResult.kind === 'ok' && Array.isArray(okResult.value) ? okResult.value.length : -1;
  lines.push(`products.json → 成功（配列・${count}件）`);

  const ngResult = await readJsonSafely('missing.json');
  lines.push(
    ngResult.kind === 'ok'
      ? 'missing.json → 成功'
      : `missing.json → 失敗（${describeShopError(ngResult.error)}）`
  );

  const raw = await tryCatchAsync(() => loadFixtureText('missing.json'));
  const chain = raw.kind === 'error' ? describeErrorChain(raw.error) : '';
  lines.push(`原因の連鎖に ENOENT を含む: ${chain.includes('ENOENT')}`);
  lines.push(`原因の連鎖の先頭: ${chain.split(' <- ')[0] ?? '(なし)'}`);
  lines.push(`必ずあるはずの商品: ${mustFindItem(catalog, 3).name}`);

  try {
    mustFindItem(catalog, 99);
    lines.push('起きないはずの失敗: 起きなかった');
  } catch (caught: unknown) {
    lines.push(`起きないはずの失敗: ${toError(caught).name}: ${toMessage(caught)}`);
  }
  return lines.join('\n');
}

checkString(
  '問題5: 出力6行',
  await solveQ5(),
  'products.json → 成功（配列・5件）\n' +
    'missing.json → 失敗（商品カタログを読み込めませんでした' +
    '（データの読み込みに失敗しました: missing.json））\n' +
    '原因の連鎖に ENOENT を含む: true\n' +
    '原因の連鎖の先頭: FixtureReadError: データの読み込みに失敗しました: missing.json\n' +
    '必ずあるはずの商品: マグカップ\n' +
    '起きないはずの失敗: InvariantError: ' +
    'カタログに必ずあるはずの商品が見つかりません: 商品が見つかりません（productId: 99）'
);

// ---------------------------------------------------------------------------
// 問題6：ログの安全化と失敗の集約
// ---------------------------------------------------------------------------
function maskSensitiveDeep(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item: unknown) => maskSensitiveDeep(item));
  }
  if (typeof value === 'object' && value !== null) {
    const masked: Record<string, unknown> = {};

    for (const [key, child] of Object.entries(value)) {
      masked[key] = isSensitiveKey(key) ? '[REDACTED]' : maskSensitiveDeep(child);
    }
    return masked;
  }
  return value;
}

function toLogLine(
  event: string,
  context: Record<string, unknown>,
  failures: readonly ShopError[]
): string {
  return JSON.stringify({
    event,
    failures: failures.length,
    context: maskSensitiveDeep(context),
  });
}

async function solveQ6(): Promise<string> {
  const lines: string[] = [];
  const body: unknown = {
    email: 'taro@example.com',
    password: 'hunter2',
    profile: { name: '太郎', sessionToken: 'tok_abc' },
    items: [{ productId: 3, cardNumber: '4242424242424242' }],
  };

  lines.push(JSON.stringify(maskSensitiveDeep(body)));

  const result = await buildReservations(failureRequests);

  if (result.kind === 'error') {
    lines.push(
      `失敗${result.error.length}件: ` +
        result.error.map((error) => describeShopError(error)).join(' / ')
    );
    lines.push(
      toLogLine(
        'reservation_failed',
        { userId: 42, requestId: 'req-001', password: 'hunter2' },
        result.error
      )
    );
  } else {
    lines.push('失敗はありませんでした');
  }
  return lines.join('\n');
}

checkString(
  '問題6: 出力3行',
  await solveQ6(),
  '{"email":"taro@example.com","password":"[REDACTED]",' +
    '"profile":{"name":"太郎","sessionToken":"[REDACTED]"},' +
    '"items":[{"productId":3,"cardNumber":"[REDACTED]"}]}\n' +
    '失敗2件: リネンのふきんの在庫が足りません（希望 1点 / 在庫 0点） / ' +
    '商品が見つかりません（productId: 99）\n' +
    '{"event":"reservation_failed","failures":2,' +
    '"context":{"userId":42,"requestId":"req-001","password":"[REDACTED]"}}'
);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session18: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session18: ok');
