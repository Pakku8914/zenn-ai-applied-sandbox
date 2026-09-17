// 復習03「セッション16〜19の横断復習」の練習問題の解答を検証する。
// 章に載せた「期待される出力」と1文字でも違えばエラー終了する。
//
// 問題2と問題6のテストは vitest 側（review03.test.ts）でも走る。
// 実行: docker compose exec ts npx tsx src/review03/verify.ts

import { findProductById, isWithinQuantityLimit } from '../session16/cart';
import { buildPaymentSummary, calcShippingFee, resolveDiscountRule } from '../session16/pricing';
import type { CartLine } from '../session16/types';
import { delayWithSignal } from '../session17/async-tools';
import { loadJsonText, loadProducts, reserveStockStub } from '../session17/catalog';
import type { Product } from '../session17/catalog';
import { describeRank } from './q3-rank';
import { resolveRuleBySpent } from './q3-discount';
import { DataError } from './shared';
import type { Result } from './shared';
import {
  describeError,
  formatLogLine,
  formatParseError,
  getActiveLoads,
  loadCount,
  loadProductReport,
  loadWithRetry,
  parseCategories,
  parseProducts,
  reserveAllSequential,
  reserveAllSettled,
  summarizeReservations,
} from './solutions';
import type { JsonReader, LoadContext } from './solutions';

/** 比較できる値 */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}`);
    console.error(`  期待値: ${String(expected)}`);
    console.error(`  実際　: ${String(actual)}`);
    process.exit(1);
  }
};

/** マスタから明細を1行作る（セッション16のモジュールをそのまま使う） */
const line = (productId: number, quantity: number): CartLine => {
  const product = findProductById(productId);
  if (product === undefined) {
    throw new Error(`商品マスタが壊れています: id=${productId}`);
  }
  return { product, quantity };
};

/** 検証で使う正しい1件（fixtures の1番目と同じ値） */
const BASE_PRODUCT = {
  id: 1,
  name: 'ラベンダーの石けん',
  price: 480,
  stock: 24,
  description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
  imageUrl: '/images/products/lavender-soap.png',
  categoryId: 1,
};

// 共通の前提を確認する
check('共通: マスタの値', line(3, 1).product.price, 2350);
check('共通: 送料は税込商品合計で判定（2999円）', calcShippingFee(2999), 500);
check('共通: 送料は税込商品合計で判定（3000円）', calcShippingFee(3000), 0);

// ---------------------------------------------------------------------------
// 問題1：この catch は危険（S18・S16・S12）
// ---------------------------------------------------------------------------
const q1Context: LoadContext = {
  userId: 1,
  token: 'secret-token-abc',
  endpoint: '/api/products',
};

const q1Format = (label: string, result: Result<number, string>): string =>
  result.kind === 'ok' ? `${label} 成功 → ${result.value}件` : `${label} 失敗 → ${result.error}`;

const q1Ok = await loadCount(async () => ['石けん', 'ハンドクリーム', 'マグカップ']);
const q1DataError = await loadCount(async () => {
  throw new DataError('products.json が壊れています', {
    cause: new SyntaxError('Unexpected end of JSON input'),
  });
});
const q1StringThrown = await loadCount(async () => {
  throw 'タイムアウト';
});
const q1ObjectThrown = await loadCount(async () => {
  throw { code: 500 };
});

// @ts-expect-error unknown のまま message は読めない
const q1Peek = (error: unknown): unknown => error.message;
check('問題1: unknown を絞り込まずに読むと型エラー', String(q1Peek(new Error('x'))), 'x');

const q1Lines = [
  q1Format('①', q1Ok),
  q1Format('②', q1DataError),
  q1Format('③', q1StringThrown),
  q1Format('④', q1ObjectThrown),
  formatLogLine(q1Context, 'タイムアウト'),
  `実行中の件数: ${getActiveLoads()}`,
];

check('問題1: トークンはログに出ない', formatLogLine(q1Context, 'x').includes('secret'), false);
check(
  '問題1の出力',
  q1Lines.join('\n'),
  [
    '① 成功 → 3件',
    '② 失敗 → DataError: products.json が壊れています / 原因: SyntaxError: Unexpected end of JSON input',
    '③ 失敗 → 文字列が投げられました: タイムアウト',
    '④ 失敗 → 不明なエラー: {"code":500}',
    '[取得失敗] 文字列が投げられました: タイムアウト / {"userId":1,"endpoint":"/api/products"}',
    '実行中の件数: 0',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題2：境界値のテスト（数値そのものは vitest 側でも検証する）
// ---------------------------------------------------------------------------
check('問題2: 数量0は範囲外', isWithinQuantityLimit(line(1, 0)), false);
check('問題2: 数量1は範囲内', isWithinQuantityLimit(line(1, 1)), true);
check('問題2: 数量10は範囲内', isWithinQuantityLimit(line(1, 10)), true);
check('問題2: 数量11は範囲外', isWithinQuantityLimit(line(1, 11)), false);

const q2SoapOnly = buildPaymentSummary([line(1, 5)], resolveDiscountRule('none'));
check('問題2: 税抜2400円の税込', q2SoapOnly.totalWithTax, 2640);
check('問題2: 税抜2400円の送料', q2SoapOnly.shippingFee, 500);
check('問題2: 税抜2400円の支払総額', q2SoapOnly.payableAmount, 3140);

const q2Mixed = buildPaymentSummary([line(1, 2), line(2, 1)], resolveDiscountRule('none'));
check('問題2: 税抜2760円の税込', q2Mixed.totalWithTax, 3036);
check('問題2: 税抜2760円の送料', q2Mixed.shippingFee, 0);
check('問題2: 税抜2760円の支払総額', q2Mixed.payableAmount, 3036);

const q2NoDiscount = buildPaymentSummary([line(3, 1), line(1, 1)], resolveDiscountRule('none'));
check('問題2: 割引なしの税込', q2NoDiscount.totalWithTax, 3113);
check('問題2: 割引なしの支払総額', q2NoDiscount.payableAmount, 3113);

const q2Gold = buildPaymentSummary([line(3, 1), line(1, 1)], resolveDiscountRule('gold'));
check('問題2: gold の割引額', q2Gold.discountAmount, 283);
check('問題2: gold の消費税', q2Gold.tax, 254);
check('問題2: gold の税込商品合計', q2Gold.totalWithTax, 2801);
check('問題2: gold は送料がかかる', q2Gold.shippingFee, 500);
check('問題2: gold の支払総額は割引なしより高い', q2Gold.payableAmount, 3301);

// ---------------------------------------------------------------------------
// 問題3：循環参照を解いたモジュール（S16）
// ---------------------------------------------------------------------------
const RANKS = ['gold', 'silver', 'bronze', 'none'] as const;

const q3Lines = [
  RANKS.map((rank) => describeRank(rank)).join(' / '),
  `累計21000円 → ${describeRank('silver')} / 小計3310円の割引額 ${resolveRuleBySpent(21000)(3310)}円`,
];

check(
  '問題3の出力',
  q3Lines.join('\n'),
  [
    'gold（10%割引） / silver（5%割引） / bronze（3%割引） / none（0%割引）',
    '累計21000円 → silver（5%割引） / 小計3310円の割引額 165円',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題4：unknown な JSON を検証して Result で返す（S16・S12・S13・S18）
// ---------------------------------------------------------------------------
const q4Any: Product = JSON.parse('{"id":1}');
check('問題4: any は型チェックをすり抜ける', String(q4Any.name), 'undefined');

const q4Cases: readonly { label: string; text: string }[] = [
  { label: '① 正しい1件', text: JSON.stringify([BASE_PRODUCT]) },
  { label: '② JSON が壊れている', text: '[{"id":1,' },
  { label: '③ 配列ではない', text: JSON.stringify(BASE_PRODUCT) },
  { label: '④ price が無い', text: JSON.stringify([{ ...BASE_PRODUCT, price: undefined }]) },
  {
    label: '⑤ price が文字列',
    text: JSON.stringify([BASE_PRODUCT, { ...BASE_PRODUCT, id: 2, price: '480' }]),
  },
];

const q4Lines = q4Cases.map((testCase) => {
  const parsed = parseProducts(testCase.text);
  if (parsed.kind === 'error') {
    return `${testCase.label} → NG ${formatParseError(parsed.error)}`;
  }
  const first = parsed.value.at(0);
  return `${testCase.label} → OK ${parsed.value.length}件（${first?.name ?? '(なし)'}）`;
});

const q4Products = parseProducts(await loadJsonText('products.json'));
const q4Categories = parseCategories(await loadJsonText('categories.json'));

if (q4Products.kind === 'error' || q4Categories.kind === 'error') {
  console.error('[NG] fixtures の JSON を検証できませんでした');
  process.exit(1);
}

const q4Kitchen = q4Categories.value.find((category) => category.id === 2);
q4Lines.push(
  `⑥ fixtures の products.json → OK ${q4Products.value.length}件（合計在庫${q4Products.value.reduce(
    (total, product) => total + product.stock,
    0
  )}点）`,
  `⑦ fixtures の categories.json → OK ${q4Categories.value.length}件（${
    q4Kitchen === undefined ? '(なし)' : `${q4Kitchen.name} = ${q4Kitchen.slug}`
  }）`
);

check(
  '問題4の出力',
  q4Lines.join('\n'),
  [
    '① 正しい1件 → OK 1件（ラベンダーの石けん）',
    '② JSON が壊れている → NG JSON として読めません（先頭: [{"id":1,）',
    '③ 配列ではない → NG 配列ではありません',
    '④ price が無い → NG 1件目の price がありません',
    '⑤ price が文字列 → NG 2件目の price の値が不正です（"480"）',
    '⑥ fixtures の products.json → OK 5件（合計在庫44点）',
    '⑦ fixtures の categories.json → OK 3件（キッチン雑貨 = kitchen）',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題5：ループの中の await をやめる（S17・S18・S13）
// ---------------------------------------------------------------------------
const q5Products = await loadProducts();

let q5Running = 0;
let q5MaxRunning = 0;
let q5Calls = 0;

// セッション17の reserveStockStub（在庫0なら例外）を包み、同時実行数を数える
const q5Reserve = async (product: Product): Promise<string> => {
  q5Calls += 1;
  q5Running += 1;
  q5MaxRunning = Math.max(q5MaxRunning, q5Running);

  try {
    return await reserveStockStub(product);
  } finally {
    q5Running -= 1;
  }
};

let q5SequentialNote = '';
try {
  await reserveAllSequential(q5Products, q5Reserve);
  q5SequentialNote = '最後まで成功しました';
} catch (error: unknown) {
  q5SequentialNote = `${q5Calls}件目で中断（${describeError(error)}）`;
}
const q5SequentialMax = q5MaxRunning;

q5MaxRunning = 0;
q5Calls = 0;
const q5Outcomes = await reserveAllSettled(q5Products, q5Reserve);

const q5Lines = [
  `逐次（for の中で await）: 最大同時実行 ${q5SequentialMax}件 / ${q5SequentialNote}`,
  `並行（Promise.allSettled）: 最大同時実行 ${q5MaxRunning}件 / ${q5Calls}件すべて実行`,
  ...summarizeReservations(q5Outcomes),
];

check('問題5: 逐次は1件ずつ', q5SequentialMax, 1);
check('問題5: 並行は同時に走る', q5MaxRunning, 5);
check(
  '問題5の出力',
  q5Lines.join('\n'),
  [
    '逐次（for の中で await）: 最大同時実行 1件 / 4件目で中断（Error: 在庫がありません）',
    '並行（Promise.allSettled）: 最大同時実行 5件 / 5件すべて実行',
    '成功4件 / 失敗1件',
    '成功: ラベンダーの石けん / ハンドクリーム / マグカップ / コットンのトートバッグ',
    '失敗: リネンのふきん（Error: 在庫がありません）',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題6：タイムアウトとリトライ（S17・S18・S19）
// ---------------------------------------------------------------------------
const q6Retries: string[] = [];

// 2回目までは 200ms かかり、3回目以降は 5ms で終わる処理（中断に対応している）
let q6Calls = 0;
const q6Task = async (signal: AbortSignal): Promise<string> => {
  q6Calls += 1;
  const ms = q6Calls <= 2 ? 200 : 5;
  await delayWithSignal(ms, signal);
  return `成功（${q6Calls}回目・${ms}ms）`;
};

const q6Result = await loadWithRetry(
  q6Task,
  { timeoutMs: 30, retries: 2, baseMs: 1 },
  (attempt, waitMs) => {
    q6Retries.push(`${attempt}回目の失敗 → ${waitMs}ms 待つ`);
  }
);

let q6NoRetryCalls = 0;
const q6NoRetry = await loadWithRetry(
  async (signal) => {
    q6NoRetryCalls += 1;
    await delayWithSignal(200, signal);
    return '成功';
  },
  { timeoutMs: 20, retries: 0, baseMs: 1 }
);

const q6Lines = [
  ...q6Retries,
  `リトライあり: ${q6Result.kind === 'ok' ? `OK ${q6Result.value}` : `NG ${q6Result.error}`}`,
  `リトライなし: ${q6NoRetry.kind === 'ok' ? `OK ${q6NoRetry.value}` : `NG ${q6NoRetry.error}`}`,
  `試行回数: リトライあり ${q6Calls}回 / リトライなし ${q6NoRetryCalls}回`,
];

check(
  '問題6の出力',
  q6Lines.join('\n'),
  [
    '1回目の失敗 → 1ms 待つ',
    '2回目の失敗 → 2ms 待つ',
    'リトライあり: OK 成功（3回目・5ms）',
    'リトライなし: NG 制限時間 20ms を超えました',
    '試行回数: リトライあり 3回 / リトライなし 1回',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題7：読み込み → 検証 → 変換 → 集計 → レポート（S16〜S19 の総合）
// ---------------------------------------------------------------------------
const q7Options = { timeoutMs: 500, retries: 1, baseMs: 5 };
const q7Report = await loadProductReport(q7Options);

if (q7Report.kind === 'error') {
  console.error(`[NG] レポートの作成に失敗しました: ${q7Report.error}`);
  process.exit(1);
}

const q7BrokenReader: JsonReader = async (fileName) =>
  fileName === 'products.json'
    ? JSON.stringify([{ ...BASE_PRODUCT, price: '480' }])
    : loadJsonText(fileName);

const q7FailingReader: JsonReader = async (fileName) => {
  if (fileName === 'products.json') {
    throw new Error('ファイルが見つかりません');
  }
  return loadJsonText(fileName);
};

const q7SlowReader: JsonReader = async (fileName, signal) => {
  await delayWithSignal(200, signal);
  return loadJsonText(fileName);
};

const q7Broken = await loadProductReport({ ...q7Options, retries: 0 }, q7BrokenReader);
const q7Failing = await loadProductReport({ ...q7Options, retries: 0 }, q7FailingReader);
const q7Slow = await loadProductReport({ timeoutMs: 20, retries: 0, baseMs: 1 }, q7SlowReader);

const q7Lines = [
  ...q7Report.value,
  `① 壊れた JSON → ${q7Broken.kind === 'error' ? `NG ${q7Broken.error}` : 'OK'}`,
  `② 読み込み失敗 → ${q7Failing.kind === 'error' ? `NG ${q7Failing.error}` : 'OK'}`,
  `③ 制限時間 20ms → ${q7Slow.kind === 'error' ? `NG ${q7Slow.error}` : 'OK'}`,
];

check(
  '問題7の出力',
  q7Lines.join('\n'),
  [
    '=== 商品カタログ レポート ===',
    'バス・ボディケア: 2件 / 在庫金額 33120円',
    'キッチン雑貨: 1件 / 在庫金額 7050円',
    'ファブリック: 2件 / 在庫金額 14000円',
    '在庫切れ: リネンのふきん',
    '合計: 5件 / 54170円',
    '① 壊れた JSON → NG 1件目の price の値が不正です（"480"）',
    '② 読み込み失敗 → NG DataError: products.json を読み込めません / 原因: Error: ファイルが見つかりません',
    '③ 制限時間 20ms → NG 制限時間 20ms を超えました',
  ].join('\n')
);

console.log('review03: ok');
