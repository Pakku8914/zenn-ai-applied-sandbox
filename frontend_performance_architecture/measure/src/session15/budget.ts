import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { CONDITIONS, measureMedian } from '../vitals-client.ts';

/**
 * S15：パフォーマンス予算の定義と判定、計測結果の履歴と差分。
 * 判定と差分は純粋関数にしてあるので、ブラウザを起動せずに固定値で検査できる。
 */

/** 本書では 1KB = 1,000 バイトとする（1,024 バイトは KiB と書いて区別する）。 */
export const KB = 1_000;

export type Metric = 'jsBytes' | 'LCP' | 'INP' | 'CLS';
export const METRICS: readonly Metric[] = ['jsBytes', 'LCP', 'INP', 'CLS'];
export const LABELS: Record<Metric, string> = {
  jsBytes: '初期 JS',
  LCP: 'LCP 中央値',
  INP: 'INP 中央値',
  CLS: 'CLS 中央値',
};

export type Budget = { metric: Metric; max: number };

/**
 * 本章の予算。出発点の実測（初期 JS 約 202,000 バイト・LCP 中央値 約 700ms）に余裕を足して決めた。
 * バイト数は決定的なので余裕を小さく、時間は揺れるので余裕を大きく取る。
 */
export const BUDGETS: readonly Budget[] = [
  { metric: 'jsBytes', max: 250 * KB },
  { metric: 'LCP', max: 1_000 },
];

export type Status = 'pass' | 'fail' | 'missing';
export type BudgetResult = Budget & { actual: number | undefined; status: Status };
export type Values = Partial<Record<Metric, number>>;

/** 予算ごとに合否を決める。上限ちょうどは合格。測れなかった指標は合格にしない（missing）。 */
export function evaluate(values: Values, budgets: readonly Budget[] = BUDGETS): BudgetResult[] {
  return budgets.map((budget) => {
    const actual = values[budget.metric];
    const status: Status =
      actual === undefined || !Number.isFinite(actual) ? 'missing' : actual <= budget.max ? 'pass' : 'fail';
    return { ...budget, actual, status };
  });
}

export const passed = (results: readonly BudgetResult[]): boolean => results.every((r) => r.status === 'pass');

export function formatValue(metric: Metric, value: number | undefined): string {
  if (value === undefined) return 'なし';
  if (metric === 'CLS') return value.toFixed(3);
  const n = Math.round(value).toLocaleString('en-US');
  return metric === 'jsBytes' ? `${n} バイト` : `${n}ms`;
}

/** 判定結果を1行ずつの文字列にする（CI のログでそのまま読める形） */
export function formatResults(results: readonly BudgetResult[]): string {
  return results
    .map((r) => {
      const head = `${r.status === 'pass' ? 'OK  ' : 'NG  '}${LABELS[r.metric]}: ${formatValue(r.metric, r.actual)}`;
      const limit = `予算 ${formatValue(r.metric, r.max)}`;
      if (r.actual === undefined) return `${head}（${limit}・計測できませんでした）`;
      const rest = r.max - r.actual;
      return `${head}（${limit}・${rest >= 0 ? '残り' : '超過'} ${formatValue(r.metric, Math.abs(rest))}）`;
    })
    .join('\n');
}

// ---- 計測の記録（履歴） ----

export const CONDITIONS_LABEL =
  `CPU ${CONDITIONS.cpuThrottlingRate}倍スロットリング / ` +
  `${CONDITIONS.network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${CONDITIONS.network.latencyMs}ms / 本番ビルド`;

export type BudgetRecord = {
  name: string;
  url: string;
  measuredAt: string;
  /** どの変更で計測したか。CI では GITHUB_SHA などを入れる */
  commit: string;
  conditions: string;
  runs: number;
  median: Values;
  /** 各回の値。ばらつきを後から確かめられるように中央値と一緒に残す */
  samples: Partial<Record<Metric, number[]>>;
};

/** URL を runs 回計測し、中央値と各回の値を記録の形にまとめる */
export async function measureRecord(name: string, url: string, runs = 3): Promise<BudgetRecord> {
  const result = await measureMedian(url, { runs });
  const median: Values = {};
  const samples: Partial<Record<Metric, number[]>> = {};
  for (const metric of METRICS) {
    const values =
      metric === 'jsBytes'
        ? result.runs.map((r) => r.jsBytes)
        : result.runs.flatMap((r) => r.vitals.filter((v) => v.name === metric).map((v) => v.value));
    const m = result.median[metric];
    if (values.length > 0 && m !== undefined) {
      samples[metric] = values;
      median[metric] = m;
    }
  }
  return {
    name,
    url,
    measuredAt: new Date().toISOString(),
    commit: process.env.GITHUB_SHA ?? process.env.GIT_COMMIT ?? 'unknown',
    conditions: CONDITIONS_LABEL,
    runs,
    median,
    samples,
  };
}

/** 記録の名前はファイル名になる。外から渡る値なので、パスとして危険な文字を受け付けない */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function historyFile(dir: string, name: string): string {
  if (!NAME_PATTERN.test(name)) {
    throw new Error(`記録の名前「${name}」は使えません（英小文字・数字・ハイフンのみ、64 文字まで）`);
  }
  return join(dir, `${name}.jsonl`);
}

/** 1行に1記録（JSON Lines）。追記だけなので、過去の記録を上書きで失わない */
export function appendRecord(dir: string, record: BudgetRecord): void {
  const file = historyFile(dir, record.name);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
    // 計測結果は生成物。誤ってコミットしないよう、ディレクトリごと Git の対象外にする
    writeFileSync(join(dir, '.gitignore'), '*\n');
  }
  appendFileSync(file, `${JSON.stringify(record)}\n`);
}

export function loadHistory(dir: string, name: string): BudgetRecord[] {
  const file = historyFile(dir, name);
  if (!existsSync(file)) return [];
  return readFileSync(file, 'utf8')
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line, i) => {
      try {
        return JSON.parse(line) as BudgetRecord;
      } catch {
        throw new Error(`${file} の ${i + 1} 行目が JSON として読めません`);
      }
    });
}

// ---- 前回との差分 ----

/**
 * 「要確認」とみなす増え方。予算（落とす）とは別に、差分（知らせる）の感度を決める。
 * バイト数は決定的なので小さな増加も拾い、時間は揺れるので比率で大きめに取る。
 */
export const REGRESSION_TOLERANCE: Record<Metric, { abs?: number; ratio?: number }> = {
  jsBytes: { abs: 1 * KB },
  LCP: { ratio: 0.2 },
  INP: { ratio: 0.2 },
  CLS: { abs: 0.05 },
};

export function isRegressed(metric: Metric, previous: number, current: number): boolean {
  const { abs, ratio } = REGRESSION_TOLERANCE[metric];
  const delta = current - previous;
  if (abs !== undefined && delta > abs) return true;
  if (ratio !== undefined && previous > 0 && delta / previous > ratio) return true;
  return false;
}

export type DiffRow = {
  metric: Metric;
  previous: number | undefined;
  current: number | undefined;
  delta: number | undefined;
  regressed: boolean;
};

export function diffRecords(
  previous: BudgetRecord | undefined,
  current: BudgetRecord,
  metrics: readonly Metric[] = BUDGETS.map((b) => b.metric),
): DiffRow[] {
  return metrics.map((metric) => {
    const before = previous?.median[metric];
    const after = current.median[metric];
    if (before === undefined || after === undefined) {
      return { metric, previous: before, current: after, delta: undefined, regressed: false };
    }
    return { metric, previous: before, current: after, delta: after - before, regressed: isRegressed(metric, before, after) };
  });
}

function formatDelta(row: DiffRow): string {
  if (row.delta === undefined || row.previous === undefined) return '—';
  const sign = row.delta >= 0 ? '+' : '-';
  const pct = row.previous === 0 ? '' : `（${sign}${Math.abs((row.delta / row.previous) * 100).toFixed(1)}%）`;
  return `${sign}${formatValue(row.metric, Math.abs(row.delta))}${pct}`;
}

/** 差分を Markdown の表にする。CI のログにも、プルリクエストのコメントにもそのまま貼れる */
export function formatDiff(previous: BudgetRecord | undefined, current: BudgetRecord): string {
  if (previous === undefined) return '前回の記録がありません（今回の結果を基準として保存します）';
  const lines = [
    `前回との差（前回 ${previous.measuredAt}・commit ${previous.commit}）`,
    '| 指標 | 前回 | 今回 | 差 | 判定 |',
    '| :--- | ---: | ---: | ---: | :--- |',
    ...diffRecords(previous, current).map(
      (row) =>
        `| ${LABELS[row.metric]} | ${formatValue(row.metric, row.previous)} | ${formatValue(row.metric, row.current)} | ` +
        `${formatDelta(row)} | ${row.regressed ? '要確認' : '—'} |`,
    ),
  ];
  return lines.join('\n');
}
