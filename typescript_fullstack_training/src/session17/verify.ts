// セッション17「非同期処理」の検証スクリプト。
//
// 本文（060）と練習問題の解答（062）に載せたコードと同じロジックを実行し、
// 章に書いた「期待される出力」と一致するかを確認する。
// 1つでも一致しなければ非0で終了する。
//
// console.log を1行ずつ出す章のコードは、この検証では
// 「出力行を \n でつないだ文字列」を返す関数として表現している。
//
// 時間の計測結果（ミリ秒）は環境によって前後するため、
// 「並行のほうが逐次より短い」ことだけを検証し、秒数そのものは比較しない。
//
// 実行: docker compose exec ts npx tsx src/session17/verify.ts

import { readFile as readFileCallback } from 'node:fs';
import { readFile } from 'node:fs/promises';
import {
  createFlakyTask,
  createSlowThenFastTask,
  delay,
  delayWithSignal,
  isAbortLike,
  measureMs,
  retryWithBackoff,
  withTimeout,
} from './async-tools';
import {
  buildCatalog,
  formatCatalogItem,
  loadCatalog,
  loadCategories,
  loadJsonText,
  loadProducts,
  readProductPages,
  reserveStockStub,
} from './catalog';
import type { Product } from './catalog';
import { fixturePath } from './fixtures-path';

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

/** JSON テキストの要素数を数える（配列でなければ0） */
function countItems(text: string): number {
  const value: unknown = JSON.parse(text);
  return Array.isArray(value) ? value.length : 0;
}

function requireProduct(products: readonly Product[], id: number): Product {
  const product = products.find((item) => item.id === id);

  if (product === undefined) {
    throw new Error(`商品が見つかりません: id=${id}`);
  }
  return product;
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : '不明なエラー';
}

const catalogExpected = [
  'ラベンダーの石けん（バス・ボディケア）480円 / 在庫24点',
  'ハンドクリーム（バス・ボディケア）1800円 / 在庫12点',
  'マグカップ（キッチン雑貨）2350円 / 在庫3点',
  'リネンのふきん（ファブリック）990円 / 在庫切れ',
  'コットンのトートバッグ（ファブリック）2800円 / 在庫5点',
].join('\n');

// ---------------------------------------------------------------------------
// 本文 1節：イベントループの並び方（同期 → マイクロタスク → タスク）
// ---------------------------------------------------------------------------
async function bodyEventLoopOrder(): Promise<string> {
  const lines: string[] = [];

  lines.push('1: 同期');
  setTimeout(() => {
    lines.push('4: タスクキュー（setTimeout）');
  }, 0);
  Promise.resolve().then(() => {
    lines.push('3: マイクロタスクキュー（Promise）');
  });
  lines.push('2: 同期');

  await delay(20);
  return lines.join('\n');
}

checkString(
  '本文1節: イベントループの並び方',
  await bodyEventLoopOrder(),
  '1: 同期\n2: 同期\n3: マイクロタスクキュー（Promise）\n4: タスクキュー（setTimeout）'
);

// ---------------------------------------------------------------------------
// 本文 2節：コールバック → then → async/await（同じ処理を3通り）
// ---------------------------------------------------------------------------
function loadByCallback(): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    readFileCallback(fixturePath('products.json'), 'utf-8', (productsError, productsText) => {
      if (productsError !== null) {
        reject(productsError);
        return;
      }

      readFileCallback(
        fixturePath('categories.json'),
        'utf-8',
        (categoriesError, categoriesText) => {
          if (categoriesError !== null) {
            reject(categoriesError);
            return;
          }
          resolve(`商品${countItems(productsText)}件 / カテゴリ${countItems(categoriesText)}件`);
        }
      );
    });
  });
}

function loadByThen(): Promise<string> {
  let productCount = 0;

  return readFile(fixturePath('products.json'), 'utf-8')
    .then((text) => {
      productCount = countItems(text);
      return readFile(fixturePath('categories.json'), 'utf-8');
    })
    .then((text) => `商品${productCount}件 / カテゴリ${countItems(text)}件`);
}

async function loadByAsync(): Promise<string> {
  const [productsText, categoriesText] = await Promise.all([
    readFile(fixturePath('products.json'), 'utf-8'),
    readFile(fixturePath('categories.json'), 'utf-8'),
  ]);

  return `商品${countItems(productsText)}件 / カテゴリ${countItems(categoriesText)}件`;
}

const threeStyles = '商品5件 / カテゴリ3件';
checkString('本文2節: コールバック版', await loadByCallback(), threeStyles);
checkString('本文2節: then 版', await loadByThen(), threeStyles);
checkString('本文2節: async/await 版', await loadByAsync(), threeStyles);

// ---------------------------------------------------------------------------
// 本文 3節：resolve と reject（Promise を自分で作る）
// ---------------------------------------------------------------------------
function checkStock(stock: number): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    if (stock > 0) {
      resolve(`在庫あり（${stock}点）`);
    } else {
      reject(new Error('在庫切れです'));
    }
  });
}

async function bodyResolveReject(): Promise<string> {
  const lines: string[] = [];
  lines.push(await checkStock(3));

  try {
    lines.push(await checkStock(0));
  } catch (error) {
    lines.push(`エラー: ${describeError(error)}`);
  }
  return lines.join('\n');
}

checkString('本文3節: resolve と reject', await bodyResolveReject(), '在庫あり（3点）\nエラー: 在庫切れです');

// ---------------------------------------------------------------------------
// 本文 4節：Awaited で Promise の中身の型を取り出す（型だけの確認）
// ---------------------------------------------------------------------------
type LoadedProducts = Awaited<ReturnType<typeof loadProducts>>;
const typedProducts: LoadedProducts = await loadProducts();
checkNumber('本文4節: Awaited で取り出した型で受け取れる', typedProducts.length, 5);

// ---------------------------------------------------------------------------
// 本文 5節：逐次と並行の時間差／ループの中の await（Bad）と map + all（Good）
// ---------------------------------------------------------------------------
const sequentialMs = await measureMs(async () => {
  await delay(30);
  await delay(30);
  await delay(30);
});

const concurrentMs = await measureMs(async () => {
  await Promise.all([delay(30), delay(30), delay(30)]);
});

checkBoolean('本文5節: 並行の合計時間は逐次より短い', concurrentMs < sequentialMs, true);

const badLoopMs = await measureMs(async () => {
  for (const ms of [30, 30, 30]) {
    await delay(ms);
  }
});

const goodMapMs = await measureMs(async () => {
  await Promise.all([30, 30, 30].map((ms) => delay(ms)));
});

checkBoolean('本文5節: map + Promise.all はループ内 await より短い', goodMapMs < badLoopMs, true);

// ---------------------------------------------------------------------------
// 本文 6節：Promise.all の落とし穴（他の処理は走り続ける）
// ---------------------------------------------------------------------------
async function bodyAllPitfall(): Promise<string> {
  const lines: string[] = [];

  const slowOk = async (): Promise<string> => {
    await delay(30);
    lines.push('遅い処理: 完了');
    return 'ok';
  };

  const fastFail = async (): Promise<string> => {
    await delay(5);
    throw new Error('速い処理: 失敗');
  };

  try {
    await Promise.all([slowOk(), fastFail()]);
  } catch (error) {
    lines.push(`Promise.all が失敗: ${describeError(error)}`);
  }

  // 失敗のあとも「遅い処理」が走り続けていることを確かめるために待つ
  await delay(60);
  return lines.join('\n');
}

checkString(
  '本文6節: Promise.all の失敗後も他の処理は走り続ける',
  await bodyAllPitfall(),
  'Promise.all が失敗: 速い処理: 失敗\n遅い処理: 完了'
);

// ---------------------------------------------------------------------------
// 本文 6節：allSettled と race
// ---------------------------------------------------------------------------
async function bodyAllSettled(): Promise<string> {
  const fileNames = ['products.json', 'missing.json', 'categories.json'];
  const results = await Promise.allSettled(fileNames.map((fileName) => loadJsonText(fileName)));

  const lines: string[] = [];
  let okCount = 0;
  let ngCount = 0;

  for (const [index, result] of results.entries()) {
    const fileName = fileNames[index] ?? '(不明)';

    if (result.status === 'fulfilled') {
      okCount += 1;
      lines.push(`${fileName}: 成功`);
    } else {
      ngCount += 1;
      lines.push(`${fileName}: 失敗`);
    }
  }

  lines.push(`成功${okCount}件 / 失敗${ngCount}件`);
  return lines.join('\n');
}

checkString(
  '本文6節: allSettled は全部の結果を集める',
  await bodyAllSettled(),
  'products.json: 成功\nmissing.json: 失敗\ncategories.json: 成功\n成功2件 / 失敗1件'
);

async function bodyRace(): Promise<string> {
  const fast = delay(5).then(() => '5msの処理');
  const slow = delay(40).then(() => '40msの処理');
  return Promise.race([slow, fast]);
}

checkString('本文6節: race は最初に決まったものを返す', await bodyRace(), '5msの処理');

// ---------------------------------------------------------------------------
// 本文 7節：AbortController によるタイムアウト
// ---------------------------------------------------------------------------
async function bodyTimeout(): Promise<string> {
  const lines: string[] = [];

  try {
    await withTimeout((signal) => delayWithSignal(5, signal), 50);
    lines.push('5ms の処理: 完了');
  } catch {
    lines.push('5ms の処理: 中断されました');
  }

  try {
    await withTimeout((signal) => delayWithSignal(200, signal), 50);
    lines.push('200ms の処理: 完了');
  } catch {
    lines.push('200ms の処理: 制限時間 50ms を超えたので中断しました');
  }

  try {
    await delayWithSignal(200, AbortSignal.timeout(50));
    lines.push('AbortSignal.timeout 版: 完了');
  } catch {
    lines.push('AbortSignal.timeout 版: 制限時間 50ms を超えたので中断しました');
  }

  return lines.join('\n');
}

checkString(
  '本文7節: タイムアウトで中断される',
  await bodyTimeout(),
  '5ms の処理: 完了\n' +
    '200ms の処理: 制限時間 50ms を超えたので中断しました\n' +
    'AbortSignal.timeout 版: 制限時間 50ms を超えたので中断しました'
);

// 中断のエラーは AbortError / TimeoutError のどちらか（name の厳密一致には依存しない）
let abortLikeSeen = false;
try {
  await delayWithSignal(200, AbortSignal.timeout(20));
} catch (error) {
  abortLikeSeen = isAbortLike(error);
}
checkBoolean('本文7節: 中断エラーとして判定できる', abortLikeSeen, true);

// ---------------------------------------------------------------------------
// 本文 8節：リトライ（指数バックオフ）
// ---------------------------------------------------------------------------
async function bodyRetry(): Promise<string> {
  const lines: string[] = [];
  const task = createFlakyTask(2);

  const message = await retryWithBackoff(
    task,
    { retries: 3, baseMs: 10 },
    (attempt, waitMs, error) => {
      lines.push(`${attempt}回目が失敗（${describeError(error)}）。${waitMs}ms 待って再試行します`);
    }
  );

  lines.push(message);
  return lines.join('\n');
}

checkString(
  '本文8節: 2回失敗して3回目で成功する',
  await bodyRetry(),
  '1回目が失敗（一時的な失敗（1回目））。10ms 待って再試行します\n' +
    '2回目が失敗（一時的な失敗（2回目））。20ms 待って再試行します\n' +
    '成功（3回目で成功）'
);

async function bodyRetryGiveUp(): Promise<string> {
  const task = createFlakyTask(10);

  try {
    return await retryWithBackoff(task, { retries: 2, baseMs: 10 });
  } catch (error) {
    return `諦めました: ${describeError(error)}`;
  }
}

checkString(
  '本文8節: 回数を使い切ったら諦める',
  await bodyRetryGiveUp(),
  '諦めました: 一時的な失敗（3回目）'
);

// ---------------------------------------------------------------------------
// 本文 9節：for await...of で非同期に反復する
// ---------------------------------------------------------------------------
async function bodyPaging(): Promise<string> {
  const lines: string[] = [];
  let page = 0;
  let total = 0;

  for await (const products of readProductPages(2)) {
    page += 1;
    total += products.length;
    lines.push(`${page}ページ目: ${products.map((product) => product.name).join(' / ')}`);
  }

  lines.push(`合計${total}件`);
  return lines.join('\n');
}

checkString(
  '本文9節: 2件ずつページングして読み出す',
  await bodyPaging(),
  '1ページ目: ラベンダーの石けん / ハンドクリーム\n' +
    '2ページ目: マグカップ / リネンのふきん\n' +
    '3ページ目: コットンのトートバッグ\n' +
    '合計5件'
);

// ---------------------------------------------------------------------------
// 本文 10節：この章の到達点（並行読み込み → カタログ）
// ---------------------------------------------------------------------------
async function bodyCatalog(): Promise<string> {
  const catalog = await loadCatalog();
  return catalog.map((item) => formatCatalogItem(item)).join('\n');
}

checkString('本文10節: カタログ一覧', await bodyCatalog(), catalogExpected);

// buildCatalog は同期関数として単体でも使える
const bodyProducts = await loadProducts();
const bodyCategories = await loadCategories();
checkString(
  '本文10節: buildCatalog は同期関数',
  buildCatalog(bodyProducts, bodyCategories)
    .map((item) => formatCatalogItem(item))
    .join('\n'),
  catalogExpected
);

// ---------------------------------------------------------------------------
// 問題1：delay と Promise の状態
// ---------------------------------------------------------------------------
async function solveQ1(): Promise<string> {
  const lines: string[] = ['待機を開始します'];
  await delay(20);
  lines.push('20ms 待ちました');
  lines.push(await checkStock(3));

  try {
    lines.push(await checkStock(0));
  } catch (error) {
    lines.push(`エラー: ${describeError(error)}`);
  }
  return lines.join('\n');
}

checkString(
  '問題1: 出力4行',
  await solveQ1(),
  '待機を開始します\n20ms 待ちました\n在庫あり（3点）\nエラー: 在庫切れです'
);

// delay の戻り値は Promise（await する前は待ち状態）
const q1Promise = delay(5);
checkBoolean('問題1: delay の戻り値は Promise', q1Promise instanceof Promise, true);
await q1Promise;

// ---------------------------------------------------------------------------
// 問題2：コールバックを async/await に書き換える
// ---------------------------------------------------------------------------
async function solveQ2(): Promise<string> {
  const products = await loadProducts();
  const soldOut = products.filter((product) => product.stock <= 0);
  const first = products[0];

  return [
    `商品を${products.length}件読み込みました`,
    `在庫切れ: ${soldOut.map((product) => product.name).join(' / ')}`,
    `最初の商品: ${first === undefined ? '(なし)' : first.name}`,
  ].join('\n');
}

checkString(
  '問題2: 出力3行',
  await solveQ2(),
  '商品を5件読み込みました\n在庫切れ: リネンのふきん\n最初の商品: ラベンダーの石けん'
);

// ---------------------------------------------------------------------------
// 問題3：逐次と並行の時間差を測る
// ---------------------------------------------------------------------------
const q3SequentialMs = await measureMs(async () => {
  for (const ms of [20, 20, 20]) {
    await delay(ms);
  }
});

const q3ConcurrentMs = await measureMs(async () => {
  await Promise.all([20, 20, 20].map((ms) => delay(ms)));
});

checkBoolean('問題3: 並行のほうが速い', q3ConcurrentMs < q3SequentialMs, true);

// 並行でも「全部終わるまで待つ」ことは変わらない（3件の結果がそろう）
const q3Results = await Promise.all([1, 2, 3].map(async (value) => {
  await delay(10);
  return value * 2;
}));
checkString('問題3: 並行実行の結果は入力の順序で並ぶ', q3Results.join(','), '2,4,6');

// ---------------------------------------------------------------------------
// 問題4：allSettled で一部失敗を許容する
// ---------------------------------------------------------------------------
async function solveQ4(): Promise<string> {
  const products = await loadProducts();
  const targets = [
    requireProduct(products, 1),
    requireProduct(products, 3),
    requireProduct(products, 4),
  ];

  const lines: string[] = [];

  try {
    await Promise.all(targets.map((product) => reserveStockStub(product)));
    lines.push('Promise.all: 全部成功しました');
  } catch (error) {
    lines.push(`Promise.all: 失敗しました（${describeError(error)}）`);
  }

  const results = await Promise.allSettled(targets.map((product) => reserveStockStub(product)));
  let okCount = 0;
  let ngCount = 0;

  for (const [index, result] of results.entries()) {
    const target = targets[index];
    const name = target === undefined ? '(不明)' : target.name;

    if (result.status === 'fulfilled') {
      okCount += 1;
      lines.push(`${name}: ${result.value}`);
    } else {
      ngCount += 1;
      lines.push(`${name}: 失敗（${describeError(result.reason)}）`);
    }
  }

  lines.push(`確保できたのは${okCount}件、失敗は${ngCount}件`);
  return lines.join('\n');
}

checkString(
  '問題4: 出力5行',
  await solveQ4(),
  'Promise.all: 失敗しました（在庫がありません）\n' +
    'ラベンダーの石けん: 確保しました（24点）\n' +
    'マグカップ: 確保しました（3点）\n' +
    'リネンのふきん: 失敗（在庫がありません）\n' +
    '確保できたのは2件、失敗は1件'
);

// ---------------------------------------------------------------------------
// 問題5：AbortController でタイムアウトを実装する
// ---------------------------------------------------------------------------
async function solveQ5(): Promise<string> {
  const lines: string[] = [];

  try {
    await withTimeout((signal) => delayWithSignal(5, signal), 30);
    lines.push('5ms の処理: 完了');
  } catch {
    lines.push('5ms の処理: 中断されました');
  }

  try {
    await withTimeout((signal) => delayWithSignal(200, signal), 30);
    lines.push('200ms の処理: 完了');
  } catch {
    lines.push('200ms の処理: 制限時間 30ms を超えたので中断しました');
  }

  try {
    await delayWithSignal(200, AbortSignal.timeout(30));
    lines.push('AbortSignal.timeout 版: 完了');
  } catch {
    lines.push('AbortSignal.timeout 版: 制限時間 30ms を超えたので中断しました');
  }

  return lines.join('\n');
}

checkString(
  '問題5: 出力3行',
  await solveQ5(),
  '5ms の処理: 完了\n' +
    '200ms の処理: 制限時間 30ms を超えたので中断しました\n' +
    'AbortSignal.timeout 版: 制限時間 30ms を超えたので中断しました'
);

// ---------------------------------------------------------------------------
// 問題6：タイムアウト付きのリトライ（指数バックオフ）
// ---------------------------------------------------------------------------
async function solveQ6(): Promise<string> {
  const lines: string[] = [];
  const task = createSlowThenFastTask();

  const message = await retryWithBackoff(
    () => withTimeout(task, 40),
    { retries: 3, baseMs: 10 },
    (attempt, waitMs) => {
      lines.push(`${attempt}回目はタイムアウト。${waitMs}ms 待って再試行します`);
    }
  );
  lines.push(message);

  lines.push('--- ずっと遅い場合 ---');
  const alwaysSlow = (signal: AbortSignal): Promise<void> => delayWithSignal(200, signal);

  try {
    await retryWithBackoff(() => withTimeout(alwaysSlow, 40), { retries: 2, baseMs: 10 });
    lines.push('成功しました');
  } catch (error) {
    lines.push(`諦めました（中断による失敗: ${isAbortLike(error)}）`);
  }

  return lines.join('\n');
}

checkString(
  '問題6: 出力5行',
  await solveQ6(),
  '1回目はタイムアウト。10ms 待って再試行します\n' +
    '2回目はタイムアウト。20ms 待って再試行します\n' +
    '成功（3回目・5ms）\n' +
    '--- ずっと遅い場合 ---\n' +
    '諦めました（中断による失敗: true）'
);

// ---------------------------------------------------------------------------
// 問題7：ページングしながらカタログを組み立てる
// ---------------------------------------------------------------------------
async function solveQ7(): Promise<string> {
  const lines: string[] = [];
  const collected: Product[] = [];
  let page = 0;

  for await (const products of readProductPages(2)) {
    page += 1;
    collected.push(...products);
    lines.push(
      `${page}ページ目（${products.length}件）: ${products.map((item) => item.name).join(' / ')}`
    );
  }
  lines.push(`読み込み完了: ${collected.length}件`);

  const categories = await loadCategories();
  const catalog = buildCatalog(collected, categories);

  lines.push('--- カタログ ---');
  for (const item of catalog) {
    lines.push(formatCatalogItem(item));
  }

  const stockValue = catalog.reduce((total, item) => total + item.price * item.stock, 0);
  const soldOutCount = catalog.filter((item) => item.stock <= 0).length;

  lines.push('--- 集計 ---');
  lines.push(`在庫金額の合計: ${stockValue}円`);
  lines.push(`在庫切れ: ${soldOutCount}件`);

  return lines.join('\n');
}

checkString(
  '問題7: 出力13行',
  await solveQ7(),
  '1ページ目（2件）: ラベンダーの石けん / ハンドクリーム\n' +
    '2ページ目（2件）: マグカップ / リネンのふきん\n' +
    '3ページ目（1件）: コットンのトートバッグ\n' +
    '読み込み完了: 5件\n' +
    '--- カタログ ---\n' +
    catalogExpected +
    '\n--- 集計 ---\n' +
    '在庫金額の合計: 54170円\n' +
    '在庫切れ: 1件'
);

// 在庫金額の内訳（解答の表に書いた数値）
checkNumber('問題7: 石けんの在庫金額', 480 * 24, 11520);
checkNumber('問題7: ハンドクリームの在庫金額', 1800 * 12, 21600);
checkNumber('問題7: マグカップの在庫金額', 2350 * 3, 7050);
checkNumber('問題7: トートバッグの在庫金額', 2800 * 5, 14000);
checkNumber('問題7: 合計', 11520 + 21600 + 7050 + 0 + 14000, 54170);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session17: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session17: ok');
