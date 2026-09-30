import {
  CONDITIONS_LABEL,
  appendRecord,
  evaluate,
  formatDiff,
  formatResults,
  historyFile,
  loadHistory,
  measureRecord,
  passed,
} from './budget.ts';

/**
 * S15：パフォーマンス予算の検査。CI から呼ぶ入口。予算違反が1つでもあれば終了コード 1 で終わる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session15/check-budget.ts [名前=URL ...]
 *   例: ... check-budget.ts catalog=http://preview.test:4173/
 * 環境変数: BUDGET_RUNS（計測回数。既定 3）/ BUDGET_HISTORY_DIR（履歴の置き場所。既定 .budget-history）
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const runs = Number(process.env.BUDGET_RUNS ?? '3');
const historyDir = process.env.BUDGET_HISTORY_DIR ?? '.budget-history';

function usage(message: string): never {
  console.error(`使い方の誤り: ${message}`);
  // 終了コード 2 は「予算違反（1）」と区別する。設定の誤りを予算違反と取り違えないため
  process.exit(2);
}

function parseTarget(arg: string): { name: string; url: string } {
  const at = arg.indexOf('=');
  if (at <= 0) usage(`「${arg}」は 名前=URL の形ではありません`);
  const url = arg.slice(at + 1);
  if (!/^https?:\/\//.test(url)) usage(`「${url}」は http(s) の URL ではありません`);
  const name = arg.slice(0, at);
  try {
    historyFile(historyDir, name); // 計測を始める前に、名前が使えるかを確かめる
  } catch (error) {
    usage((error as Error).message);
  }
  return { name, url };
}

if (!Number.isInteger(runs) || runs < 1) usage(`BUDGET_RUNS は 1 以上の整数にしてください（${process.env.BUDGET_RUNS}）`);
const args = process.argv.slice(2);
const targets = (args.length > 0 ? args : [`catalog=${TARGET}/`]).map(parseTarget);

console.log(`計測条件: ${CONDITIONS_LABEL}（各 ${runs} 回の中央値）`);
let ok = true;
for (const { name, url } of targets) {
  const record = await measureRecord(name, url, runs);
  const results = evaluate(record.median);
  console.log(`\n[${name}] ${url}`);
  console.log(formatResults(results));
  console.log('');
  console.log(formatDiff(loadHistory(historyDir, name).at(-1), record));
  // 違反した回も記録する。「いつから超えたか」を後から追えるようにするため
  appendRecord(historyDir, record);
  if (!passed(results)) ok = false;
}

if (!ok) {
  console.error('\nパフォーマンス予算を超えました。上の NG の行と、前回との差を確認してください。');
  process.exit(1);
}
console.log('\nすべての予算内です。');
