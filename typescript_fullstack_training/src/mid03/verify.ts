// 中間プロジェクト3「商品データ取得 CLI」の自己検証スクリプト。
// 章に載せた「期待される出力」と1文字でも違えばエラー終了する。
//
// 実行: docker compose exec ts npx tsx src/mid03/verify.ts

import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { delayWithSignal } from '../session17/async-tools';
import { DEFAULT_LOAD_OPTIONS, readFixtureText } from './load';
import type { JsonReader } from './load';
import { DEFAULT_CLI_OPTIONS, main, parseCliArgs, runPipeline } from './main';
import { formatOutcome } from './report';

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

/** main を呼び、画面に出た内容と終了コードを取り出す（画面出力を横取りする） */
const capture = async (argv: readonly string[]): Promise<{ code: number; out: string }> => {
  const lines: string[] = [];
  const originalLog = console.log;
  const originalError = console.error;
  console.log = (line: unknown): void => {
    lines.push(String(line));
  };
  console.error = (line: unknown): void => {
    lines.push(`(stderr) ${String(line)}`);
  };

  try {
    const code = await main(argv);
    return { code, out: lines.join('\n') };
  } finally {
    // 横取りしたままにすると、以降の check がエラーを表示できなくなる
    console.log = originalLog;
    console.error = originalError;
  }
};

// ---------------------------------------------------------------------------
// 1. 正常系：fixtures の5件からレポートを組み立てる
// ---------------------------------------------------------------------------
const success = await capture([]);

check('正常系の終了コード', success.code, 0);
check(
  '正常系のレポート',
  success.out,
  [
    '=== 商品データ取得レポート ===',
    'バス・ボディケア: 2件 / 在庫36点 / 在庫金額 33120円',
    'キッチン雑貨: 1件 / 在庫3点 / 在庫金額 7050円',
    'ファブリック: 2件 / 在庫5点 / 在庫金額 14000円',
    '---',
    '合計: 5件 / 在庫44点 / 在庫金額 54170円',
    '平均単価: 1684円',
    '在庫切れ: リネンのふきん',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 2. 壊れたデータ：3種類の失敗を実際に再現する
// ---------------------------------------------------------------------------
const broken = await capture(['--products', 'products-broken.json']);
check('JSON が壊れているときの終了コード', broken.code, 1);
check(
  'JSON が壊れているときの出力',
  broken.out,
  [
    '=== 取得に失敗しました（1件） ===',
    '- products-broken.json が JSON として読めません（先頭: [{"id": 1,）',
  ].join('\n')
);

const missingField = await capture(['--products', 'products-missing-field.json']);
check(
  'フィールドが欠けているときの出力',
  missingField.out,
  [
    '=== 取得に失敗しました（1件） ===',
    '- products-missing-field.json の2件目: price がありません',
  ].join('\n')
);

const wrongType = await capture(['--products', 'products-wrong-type.json']);
check(
  '型が違う・範囲外のときの出力（2件まとめて報告する）',
  wrongType.out,
  [
    '=== 取得に失敗しました（2件） ===',
    '- products-wrong-type.json の1件目: price の値が不正です（"480"）',
    '- products-wrong-type.json の2件目: stock が範囲外です（-3）',
  ].join('\n')
);

const badArgs = await capture(['--zzz', '1']);
check('知らないオプションの終了コード', badArgs.code, 2);
check(
  '知らないオプションの出力',
  badArgs.out,
  [
    '(stderr) 引数が不正です: 知らないオプションです: --zzz',
    '(stderr) 使い方: npx tsx src/mid03/main.ts [--products <file>] [--timeout <ms>]',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 3. 読み込みの失敗：読み込み係を差し替えて再現する（モックライブラリは不要）
// ---------------------------------------------------------------------------
const FAST = { timeoutMs: 200, retries: 0, baseMs: 1 };

const failingRead: JsonReader = async (fileName, signal) => {
  if (fileName === 'products.json') {
    throw new Error('ファイルが見つかりません');
  }
  return readFixtureText(fileName, signal);
};

const readFailed = await runPipeline({ ...DEFAULT_CLI_OPTIONS, load: FAST }, failingRead);
check(
  '読み込み失敗の出力',
  formatOutcome(readFailed).join('\n'),
  [
    '=== 取得に失敗しました（1件） ===',
    '- products.json を読み込めません（ファイルが見つかりません）',
  ].join('\n')
);

const slowRead: JsonReader = async (fileName, signal) => {
  await delayWithSignal(200, signal);
  return readFixtureText(fileName, signal);
};

const timedOut = await runPipeline(
  { ...DEFAULT_CLI_OPTIONS, load: { timeoutMs: 20, retries: 0, baseMs: 1 } },
  slowRead
);
check(
  'タイムアウトの出力（2ファイルとも中断される）',
  formatOutcome(timedOut).join('\n'),
  [
    '=== 取得に失敗しました（2件） ===',
    '- products.json の読み込みが 20ms を超えました',
    '- categories.json の読み込みが 20ms を超えました',
  ].join('\n')
);

// 1回だけ失敗する読み込み係。再試行して成功することを確かめる
let flakyCalls = 0;
const flakyRead: JsonReader = async (fileName, signal) => {
  if (fileName === 'products.json') {
    flakyCalls += 1;
    if (flakyCalls === 1) {
      throw new Error('一時的な失敗');
    }
  }
  return readFixtureText(fileName, signal);
};

const retryNotices: string[] = [];
const retried = await runPipeline(
  { ...DEFAULT_CLI_OPTIONS, load: { timeoutMs: 200, retries: 1, baseMs: 1 } },
  flakyRead,
  (fileName, attempt, waitMs) => {
    retryNotices.push(`${fileName} の${attempt}回目が失敗 → ${waitMs}ms 待つ`);
  }
);
check('再試行して成功する', retried.kind, 'ok');
check('再試行の通知は1回', retryNotices.join('\n'), 'products.json の1回目が失敗 → 1ms 待つ');
check('products.json を読んだ回数', flakyCalls, 2);

// カテゴリマスタが足りないときは、変換の段で失敗する
const partialCategories: JsonReader = async (fileName, signal) =>
  fileName === 'categories.json'
    ? JSON.stringify([{ id: 1, name: 'バス・ボディケア', slug: 'bath-body' }])
    : readFixtureText(fileName, signal);

const unknownCategory = await runPipeline(
  { ...DEFAULT_CLI_OPTIONS, load: FAST },
  partialCategories
);
check(
  '未知のカテゴリの出力',
  formatOutcome(unknownCategory).join('\n'),
  [
    '=== 取得に失敗しました（3件） ===',
    '- 「マグカップ」のカテゴリ（categoryId: 2）がマスタにありません',
    '- 「リネンのふきん」のカテゴリ（categoryId: 3）がマスタにありません',
    '- 「コットンのトートバッグ」のカテゴリ（categoryId: 3）がマスタにありません',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 4. 引数の解析と、既定の設定が書き換わらないこと
// ---------------------------------------------------------------------------
const parsedTimeout = parseCliArgs(['--timeout', '50']);
check(
  '--timeout を読み取る',
  parsedTimeout.kind === 'ok' ? parsedTimeout.value.load.timeoutMs : -1,
  50
);
check('既定の設定は書き換わらない', DEFAULT_LOAD_OPTIONS.timeoutMs, 1000);

const parsedBad = parseCliArgs(['--timeout', 'いっぱい']);
check(
  '数値でない --timeout は失敗',
  parsedBad.kind === 'error' ? parsedBad.error : '',
  '--timeout には正の整数を指定してください（いっぱい）'
);

// ---------------------------------------------------------------------------
// 5. 設計の約束：画面出力は main.ts だけに閉じ込める
// ---------------------------------------------------------------------------
const here = dirname(fileURLToPath(import.meta.url));
const PURE_MODULES = ['types.ts', 'load.ts', 'validate.ts', 'transform.ts', 'aggregate.ts', 'report.ts'];

for (const fileName of PURE_MODULES) {
  const source = await readFile(join(here, fileName), 'utf-8');
  check(`${fileName} は画面出力を持たない`, source.includes('console.'), false);
}

console.log('mid03: ok');
