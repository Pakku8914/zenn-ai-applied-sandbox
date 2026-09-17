/**
 * チーム稼働ダッシュボード ― データ層（セッション6 版）
 *
 * セッション5 の data.ts をコピーし、本章で必要な 3 つを足しています。
 *   ① 社内用語辞書（リソーステンプレートと補完の題材）
 *   ② 改訂番号 revision と稼働記録の追加（購読通知のトリガ）
 *   ③ 書き出し台帳（resources/list に何を載せるかを決める）
 *
 * アーカイブ機能はセッション5 側に置いたままにして、本章では扱いません
 * （本章のテーマはリソースとプロンプトなので、ツールは 2 本に絞ります）。
 */

export type Member = {
  readonly id: string;
  readonly name: string;
  readonly team: string;
  readonly weeklyCapacityHours: number;
};

export type Project = {
  readonly id: string;
  readonly name: string;
};

export type WorkLog = {
  readonly memberId: string;
  readonly projectId: string;
  /** YYYY-MM-DD 形式。辞書順の比較がそのまま時系列の比較になる */
  readonly date: string;
  readonly hours: number;
};

/** 1 回の集計・書き出しで扱える期間の上限（日数） */
export const MAX_RANGE_DAYS = 92;

/** 本文をレスポンスやプロンプトに埋め込んでよい上限（バイト） */
export const MAX_INLINE_BYTES = 2048;

/** 購読可能リソース dashboard://summary/current が集計する期間（固定） */
export const DASHBOARD_FROM = "2026-07-27";
export const DASHBOARD_TO = "2026-08-07";

/** 用語スラッグの許可リスト。URI に載る値はここまで狭めておく */
export const TERM_SLUG_PATTERN = /^[a-z0-9-]{1,32}$/;

/** report://weekly/{period}.csv の period の形式 */
export const PERIOD_PATTERN = /^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$/;

export const members: readonly Member[] = [
  { id: "m-001", name: "佐藤 花子", team: "platform", weeklyCapacityHours: 40 },
  { id: "m-002", name: "鈴木 一郎", team: "platform", weeklyCapacityHours: 40 },
  { id: "m-003", name: "田中 美咲", team: "data", weeklyCapacityHours: 32 },
  { id: "m-004", name: "高橋 健", team: "data", weeklyCapacityHours: 40 },
];

export const projects: readonly Project[] = [
  { id: "p-portal", name: "社内ポータル刷新" },
  { id: "p-report", name: "稼働レポート整備" },
  { id: "p-search", name: "全文検索基盤" },
];

/**
 * 稼働記録。セッション5 と違い、追加できるように可変配列にしています
 * （購読の更新通知を「明示的なトリガ」で起こすため）。
 */
const workLogs: WorkLog[] = [
  { memberId: "m-001", projectId: "p-portal", date: "2026-07-27", hours: 6 },
  { memberId: "m-002", projectId: "p-search", date: "2026-07-27", hours: 8 },
  { memberId: "m-001", projectId: "p-portal", date: "2026-07-28", hours: 7 },
  { memberId: "m-003", projectId: "p-report", date: "2026-07-29", hours: 5 },
  { memberId: "m-004", projectId: "p-search", date: "2026-07-30", hours: 4 },
  { memberId: "m-001", projectId: "p-portal", date: "2026-08-03", hours: 5 },
  { memberId: "m-002", projectId: "p-search", date: "2026-08-03", hours: 7.5 },
  { memberId: "m-003", projectId: "p-report", date: "2026-08-03", hours: 6 },
  { memberId: "m-001", projectId: "p-search", date: "2026-08-04", hours: 3 },
  { memberId: "m-002", projectId: "p-search", date: "2026-08-04", hours: 6 },
  { memberId: "m-004", projectId: "p-portal", date: "2026-08-04", hours: 8 },
  { memberId: "m-001", projectId: "p-portal", date: "2026-08-05", hours: 4 },
  { memberId: "m-003", projectId: "p-report", date: "2026-08-05", hours: 5.5 },
  { memberId: "m-004", projectId: "p-search", date: "2026-08-05", hours: 3 },
  { memberId: "m-002", projectId: "p-report", date: "2026-08-06", hours: 2 },
  { memberId: "m-004", projectId: "p-search", date: "2026-08-07", hours: 6 },
];

/**
 * 集計結果の改訂番号。データが変わるたびに 1 増やします。
 * 時刻ではなく連番にしているのは、教材の出力を再現可能にするためです
 * （実務では更新日時と併記すると、クライアント側のキャッシュ判断が楽になります）。
 */
let revision = 1;

// ------------------------------------------------------------------
// 社内用語辞書
// ------------------------------------------------------------------

export type GlossaryEntry = {
  /** URI に載る識別子。英小文字・数字・ハイフンだけに限定する */
  readonly slug: string;
  /** 人間向けの表記 */
  readonly term: string;
  readonly category: string;
  readonly definition: string;
  readonly related: readonly string[];
};

/** スラッグの昇順で持っておく（補完の候補順が安定します） */
export const glossary: readonly GlossaryEntry[] = [
  {
    slug: "capacity",
    term: "キャパシティ",
    category: "稼働管理",
    definition: "1 週間に投入できる稼働時間の上限。メンバーごとに設定します。",
    related: ["utilization", "wip"],
  },
  {
    slug: "cycle-time",
    term: "サイクルタイム",
    category: "指標",
    definition: "作業に着手してから完了するまでの経過時間。",
    related: ["lead-time", "wip"],
  },
  {
    slug: "lead-time",
    term: "リードタイム",
    category: "指標",
    definition: "依頼を受けてから完了するまでの経過時間。待ち時間を含みます。",
    related: ["cycle-time"],
  },
  {
    slug: "okr",
    term: "OKR",
    category: "目標管理",
    definition: "目標（Objective）と主要な成果（Key Results）で四半期の目標を管理する手法。",
    related: ["velocity"],
  },
  {
    slug: "oncall",
    term: "オンコール",
    category: "運用",
    definition: "障害対応の当番。稼働時間とは別枠で記録します。",
    related: ["toil", "postmortem"],
  },
  {
    slug: "postmortem",
    term: "ポストモーテム",
    category: "運用",
    definition: "障害の後に原因と再発防止策をまとめる文書。個人の責任を問わないのが原則です。",
    related: ["oncall"],
  },
  {
    slug: "sprint",
    term: "スプリント",
    category: "開発プロセス",
    definition: "1〜2 週間の固定期間。この区切りで計画と振り返りを行います。",
    related: ["velocity", "story-point"],
  },
  {
    slug: "story-point",
    term: "ストーリーポイント",
    category: "指標",
    definition: "作業量の相対見積もり単位。時間ではなく難しさの比で表します。",
    related: ["velocity", "sprint"],
  },
  {
    slug: "toil",
    term: "トイル",
    category: "運用",
    definition: "手作業で繰り返し発生し、価値を生まない運用作業。自動化の候補になります。",
    related: ["oncall"],
  },
  {
    slug: "utilization",
    term: "稼働率",
    category: "稼働管理",
    definition: "実績の稼働時間をキャパシティで割った値。100% を目標にしない指標です。",
    related: ["capacity"],
  },
  {
    slug: "velocity",
    term: "ベロシティ",
    category: "指標",
    definition: "1 スプリントで完了したストーリーポイントの合計。",
    related: ["sprint", "story-point"],
  },
  {
    slug: "wip",
    term: "WIP（Work In Progress）",
    category: "開発プロセス",
    definition: "着手済みで完了していない作業。同時に持てる上限を決めて運用します。",
    related: ["cycle-time", "capacity"],
  },
];

export function findTerm(slug: string): GlossaryEntry | undefined {
  return glossary.find((entry) => entry.slug === slug);
}

/**
 * 補完の候補を返す。入力値による絞り込みは**サーバー側の責務**です
 * （SDK は返した配列をそのままクライアントに渡します）。
 */
export function completeTermSlugs(prefix: string): string[] {
  const needle = prefix.trim().toLowerCase();
  return glossary
    .map((entry) => entry.slug)
    .filter((slug) => slug.startsWith(needle))
    .sort((a, b) => a.localeCompare(b));
}

/** 用語 1 件を Markdown にする（常に 5 行になるように組み立てます） */
export function renderTermMarkdown(entry: GlossaryEntry): string {
  return [
    `# ${entry.term}（${entry.slug}）`,
    "",
    `- 分類: ${entry.category}`,
    `- 定義: ${entry.definition}`,
    `- 関連: ${entry.related.join(", ")}`,
  ].join("\n");
}

// ------------------------------------------------------------------
// 集計と稼働記録の追加
// ------------------------------------------------------------------

export type MemberHours = {
  memberId: string;
  name: string;
  team: string;
  totalHours: number;
  workedDays: number;
};

export type HoursSummary = {
  from: string;
  to: string;
  totalHours: number;
  members: MemberHours[];
};

export function findMember(memberId: string): Member | undefined {
  return members.find((member) => member.id === memberId);
}

export function findProject(projectId: string): Project | undefined {
  return projects.find((project) => project.id === projectId);
}

export function summarizeHours(params: { from: string; to: string }): HoursSummary {
  const { from, to } = params;
  const targets = workLogs.filter((log) => log.date >= from && log.date <= to);

  const buckets = new Map<string, { hours: number; days: Set<string> }>();
  for (const log of targets) {
    const bucket = buckets.get(log.memberId) ?? { hours: 0, days: new Set<string>() };
    bucket.hours += log.hours;
    bucket.days.add(log.date);
    buckets.set(log.memberId, bucket);
  }

  const rows: MemberHours[] = [];
  for (const [id, bucket] of buckets) {
    const member = findMember(id);
    rows.push({
      memberId: id,
      name: member?.name ?? "(不明なメンバー)",
      team: member?.team ?? "(不明)",
      totalHours: roundHours(bucket.hours),
      workedDays: bucket.days.size,
    });
  }
  rows.sort((a, b) => a.memberId.localeCompare(b.memberId));

  return {
    from,
    to,
    totalHours: roundHours(rows.reduce((sum, row) => sum + row.totalHours, 0)),
    members: rows,
  };
}

export type DashboardSnapshot = {
  revision: number;
  from: string;
  to: string;
  totalHours: number;
  memberCount: number;
  members: MemberHours[];
};

/** 購読可能リソースの中身。期間を固定しているので、変わるのは revision と数値だけ */
export function getDashboardSnapshot(): DashboardSnapshot {
  const summary = summarizeHours({ from: DASHBOARD_FROM, to: DASHBOARD_TO });
  return {
    revision,
    from: summary.from,
    to: summary.to,
    totalHours: summary.totalHours,
    memberCount: summary.members.length,
    members: summary.members,
  };
}

export type AddWorkLogResult = {
  revision: number;
  entries: number;
  totalHours: number;
};

/**
 * 稼働記録を 1 件追加する。冪等ではありません（同じ内容を 2 回呼べば 2 件になります）。
 * 更新通知のトリガを「明示的な関数呼び出し」にしているのは、
 * 時刻やタイマーに依存しない再現可能な確認をするためです。
 */
export function addWorkLog(input: WorkLog): AddWorkLogResult {
  workLogs.push(input);
  revision += 1;
  return {
    revision,
    entries: workLogs.length,
    totalHours: getDashboardSnapshot().totalHours,
  };
}

// ------------------------------------------------------------------
// CSV と書き出し台帳
// ------------------------------------------------------------------

export type ReportRow = {
  date: string;
  memberId: string;
  projectId: string;
  hours: number;
};

/** 並び順は日付 → メンバー ID の昇順で固定（同じ入力なら同じバイト列になる） */
export function buildReportRows(from: string, to: string): ReportRow[] {
  return workLogs
    .filter((log) => log.date >= from && log.date <= to)
    .map((log) => ({
      date: log.date,
      memberId: log.memberId,
      projectId: log.projectId,
      hours: log.hours,
    }))
    .sort((a, b) =>
      a.date === b.date ? a.memberId.localeCompare(b.memberId) : a.date.localeCompare(b.date),
    );
}

/** 機械処理向けの CSV。列名は ASCII だけにして文字コードの事故を避ける */
export function toCsv(rows: readonly ReportRow[]): string {
  const header = "date,memberId,projectId,hours";
  const lines = rows.map(
    (row) => `${row.date},${row.memberId},${row.projectId},${formatHours(row.hours)}`,
  );
  return [header, ...lines].join("\n") + "\n";
}

/** 人が Excel で開く用の CSV。列名と値を日本語にする */
export function toExcelCsv(rows: readonly ReportRow[]): string {
  const header = "日付,メンバー,プロジェクト,時間";
  const lines = rows.map((row) => {
    const member = findMember(row.memberId);
    const project = findProject(row.projectId);
    return `${row.date},${member?.name ?? row.memberId},${project?.name ?? row.projectId},${formatHours(row.hours)}`;
  });
  return [header, ...lines].join("\n") + "\n";
}

/**
 * BOM 付き UTF-16LE に変換して base64 にする。
 * Excel は UTF-8 の CSV を開くと日本語が化けることがあるため、実務でよく使う形式です。
 */
export function toUtf16Base64(text: string): string {
  // 先頭に付ける ﻿ はバイト順マーク（BOM）です。Excel はこれを見て文字コードを判定します
  return Buffer.from(`﻿${text}`, "utf16le").toString("base64");
}

export function sumHours(rows: readonly ReportRow[]): number {
  return roundHours(rows.reduce((sum, row) => sum + row.hours, 0));
}

/** UTF-8 でのバイト数 */
export function byteSizeOf(text: string): number {
  return new TextEncoder().encode(text).length;
}

/** from から to までの日数（両端を含む）。日付として解釈できなければ NaN */
export function daysBetween(from: string, to: string): number {
  const fromMs = Date.parse(`${from}T00:00:00Z`);
  const toMs = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(fromMs) || Number.isNaN(toMs)) {
    return Number.NaN;
  }
  return Math.floor((toMs - fromMs) / 86_400_000) + 1;
}

export function formatPeriod(from: string, to: string): string {
  return `${from}_${to}`;
}

/** "2026-08-03_2026-08-07" を from / to に分解する。形式が違えば undefined */
export function parsePeriod(period: string): { from: string; to: string } | undefined {
  const matched = PERIOD_PATTERN.exec(period);
  const from = matched?.[1];
  const to = matched?.[2];
  if (from === undefined || to === undefined) {
    return undefined;
  }
  return { from, to };
}

/** export_report で書き出した期間の台帳（resources/list に載せる対象） */
const exportedPeriods = new Set<string>();

/** 台帳に登録する。新規なら true（= resources/list の中身が変わった） */
export function recordExportedPeriod(period: string): boolean {
  if (exportedPeriods.has(period)) {
    return false;
  }
  exportedPeriods.add(period);
  return true;
}

export function listExportedPeriods(): string[] {
  return [...exportedPeriods].sort((a, b) => a.localeCompare(b));
}

/**
 * プロンプト引数の補完候補にする「直近 4 週の月曜日」。
 * 現在日時から計算せず固定値にしているのは、実行した日によって
 * 教材の出力が変わらないようにするためです（実務では today から求めます）。
 */
export function listWeekStarts(): string[] {
  return ["2026-07-13", "2026-07-20", "2026-07-27", "2026-08-03"];
}

/** 月曜日から金曜日（+4 日）を求める */
export function weekEndOf(weekStart: string): string {
  const startMs = Date.parse(`${weekStart}T00:00:00Z`);
  if (Number.isNaN(startMs)) {
    return weekStart;
  }
  return new Date(startMs + 4 * 86_400_000).toISOString().slice(0, 10);
}

function formatHours(hours: number): string {
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
}

function roundHours(hours: number): number {
  return Math.round(hours * 10) / 10;
}
