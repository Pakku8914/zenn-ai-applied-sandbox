/**
 * 監査ログの集計と影響範囲の特定
 *
 * 事故の最中に書くコードではありません。**平時に書いて、テストしておく**ものです。
 * 集計が 1 行のゴミで止まらないこと、結果が決定的であることを重視しています。
 */
export type AuditRecordShape = {
  ts?: string;
  tenantId?: string;
  subject?: string;
  sessionRef?: string;
  event?: string;
  target?: string;
  outcome?: string;
  reason?: string;
  findings?: string[];
  durationMs?: number;
};

export type AuditSummary = {
  readonly total: number;
  readonly malformed: number;
  readonly byOutcome: Record<string, number>;
  readonly byTarget: Record<string, number>;
  readonly byReason: Record<string, number>;
  readonly directiveHits: number;
  readonly errorRate: number;
  readonly p95Ms: number;
};

export function parseAuditLines(lines: readonly string[]): {
  records: AuditRecordShape[];
  malformed: number;
} {
  const records: AuditRecordShape[] = [];
  let malformed = 0;
  for (const line of lines) {
    if (line.trim() === "") {
      continue;
    }
    try {
      records.push(JSON.parse(line) as AuditRecordShape);
    } catch {
      // 1 行のゴミで集計が止まってはいけない。数えて先に進む
      malformed += 1;
    }
  }
  return { records, malformed };
}

export function summarizeAuditLog(lines: readonly string[]): AuditSummary {
  const { records, malformed } = parseAuditLines(lines);
  const byOutcome: Record<string, number> = {};
  const byTarget: Record<string, number> = {};
  const byReason: Record<string, number> = {};
  const durations: number[] = [];
  let directiveHits = 0;

  for (const record of records) {
    bump(byOutcome, record.outcome ?? "unknown");
    bump(byTarget, record.target ?? "unknown");
    if (record.reason !== undefined) {
      bump(byReason, record.reason);
    }
    if ((record.findings ?? []).length > 0) {
      directiveHits += 1;
    }
    if (typeof record.durationMs === "number") {
      durations.push(record.durationMs);
    }
  }

  const parsed = records.length;
  const ok = byOutcome["ok"] ?? 0;
  // 分母から malformed を除く。解釈できない行を「エラー」に数えると、
  // ログ収集の不具合とサーバーの障害が混ざって原因が読めなくなる
  const errorRate = parsed === 0 ? 0 : round3((parsed - ok) / parsed);

  return {
    total: lines.filter((line) => line.trim() !== "").length,
    malformed,
    byOutcome: sortKeys(byOutcome),
    byTarget: sortKeys(byTarget),
    byReason: sortKeys(byReason),
    directiveHits,
    errorRate,
    p95Ms: percentile95(durations),
  };
}

/**
 * 最近傍順位法の p95。
 * 定義は複数あるので明記します（線形補間ではありません）。
 * 定義を書かない p95 は、他のシステムの p95 と比較できません。
 */
export function percentile95(values: readonly number[]): number {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1);
  return sorted[index] ?? 0;
}

export type ImpactFilter = {
  readonly subject?: string;
  readonly sessionRef?: string;
  readonly directiveId?: string;
  /** ISO 8601（Z 固定）。この時刻以降の行だけを見る */
  readonly since?: string;
};

export type ImpactReport = {
  readonly calls: number;
  readonly sessions: string[];
  readonly tenants: string[];
  readonly targets: string[];
  readonly firstSeen: string | undefined;
  readonly lastSeen: string | undefined;
};

export function findImpact(lines: readonly string[], filter: ImpactFilter): ImpactReport {
  const { records } = parseAuditLines(lines);
  const matched = records.filter((record) => {
    if (filter.subject !== undefined && record.subject !== filter.subject) {
      return false;
    }
    if (filter.sessionRef !== undefined && record.sessionRef !== filter.sessionRef) {
      return false;
    }
    if (
      filter.directiveId !== undefined &&
      !(record.findings ?? []).includes(filter.directiveId)
    ) {
      return false;
    }
    // ISO 8601（Z 固定）は辞書順がそのまま時刻順になる
    if (filter.since !== undefined && (record.ts ?? "") < filter.since) {
      return false;
    }
    return true;
  });

  const timestamps = matched
    .map((record) => record.ts ?? "")
    .filter((ts) => ts !== "")
    .sort();

  return {
    calls: matched.length,
    sessions: unique(matched.map((record) => record.sessionRef)),
    tenants: unique(matched.map((record) => record.tenantId)),
    targets: unique(matched.map((record) => record.target)),
    firstSeen: timestamps[0],
    lastSeen: timestamps[timestamps.length - 1],
  };
}

function unique(values: readonly (string | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => value !== undefined))].sort();
}

function bump(target: Record<string, number>, key: string): void {
  target[key] = (target[key] ?? 0) + 1;
}

function sortKeys(source: Record<string, number>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(source).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
  );
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}
