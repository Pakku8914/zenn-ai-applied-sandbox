/**
 * チーム稼働ダッシュボード ― データ層（セッション5 版）
 *
 * セッション3 の data.ts をコピーし、本章で必要な 3 つを足しています。
 *   ① プロジェクトのアーカイブ状態（破壊的操作の対象）
 *   ② レポート行の組み立てと CSV 化（resource_link で返す中身）
 *   ③ バイト数の計測（埋め込みにするか参照にするかの判断材料）
 *
 * セッション3 のファイルは import せず、独立したコピーとして持ちます
 * （データ層そのものを変更する章なので、前章の動くコードを壊さないため）。
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

/** 本文をレスポンスに埋め込んでよい上限（バイト）。超えたら参照だけ返す */
export const MAX_INLINE_BYTES = 2048;

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

export const workLogs: readonly WorkLog[] = [
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
 * アーカイブ済みプロジェクトの ID。
 * プロセスが生きている間だけ保持します（実務では DB の 1 カラムに相当）。
 */
const archivedProjectIds = new Set<string>();

export function findMember(memberId: string): Member | undefined {
  return members.find((member) => member.id === memberId);
}

export function listMembers(team?: string): Member[] {
  const filtered =
    team === undefined ? [...members] : members.filter((member) => member.team === team);
  return filtered.sort((a, b) => a.id.localeCompare(b.id));
}

export function findProject(projectId: string): Project | undefined {
  return projects.find((project) => project.id === projectId);
}

/** アーカイブされていないプロジェクト（ID 昇順） */
export function listActiveProjects(): Project[] {
  return projects
    .filter((project) => !archivedProjectIds.has(project.id))
    .sort((a, b) => a.id.localeCompare(b.id));
}

export function isArchived(projectId: string): boolean {
  return archivedProjectIds.has(projectId);
}

export type ArchiveResult = {
  projectId: string;
  name: string;
  /** 呼び出し前からアーカイブ済みだったか（冪等性の確認に使う） */
  alreadyArchived: boolean;
  archivedAt: string;
  affectedWorkLogs: number;
  affectedHours: number;
  remainingActiveProjects: string[];
};

/**
 * プロジェクトをアーカイブする。すでにアーカイブ済みでも成功として扱う（冪等）。
 * 稼働記録は削除しない ―― 破壊の範囲を最小限にするのは設計の意思決定です。
 */
export function archiveProject(projectId: string): ArchiveResult {
  const project = findProject(projectId);
  if (project === undefined) {
    // 呼び出し側で存在確認済みであることを前提とした防御
    throw new Error(`unknown project: ${projectId}`);
  }
  const alreadyArchived = archivedProjectIds.has(projectId);
  archivedProjectIds.add(projectId);

  const related = workLogs.filter((log) => log.projectId === projectId);
  return {
    projectId,
    name: project.name,
    alreadyArchived,
    archivedAt: new Date().toISOString(),
    affectedWorkLogs: related.length,
    affectedHours: roundHours(related.reduce((sum, log) => sum + log.hours, 0)),
    remainingActiveProjects: listActiveProjects().map((item) => item.id),
  };
}

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

export function summarizeHours(params: {
  from: string;
  to: string;
  memberId?: string;
}): HoursSummary {
  const { from, to, memberId } = params;

  const targets = workLogs.filter(
    (log) =>
      log.date >= from && log.date <= to && (memberId === undefined || log.memberId === memberId),
  );

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

export type ReportRow = {
  date: string;
  memberId: string;
  projectId: string;
  hours: number;
};

/**
 * CSV に書き出す行を組み立てる。並び順は日付 → メンバー ID の昇順で固定。
 * 順序を固定するのは、同じ入力なら同じバイト列になるようにするためです
 * （差分比較・キャッシュ・テストが安定します）。
 */
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

/** CSV 化する。列名は ASCII のみにして、文字コードの事故を避けています */
export function toCsv(rows: readonly ReportRow[]): string {
  const header = "date,memberId,projectId,hours";
  const lines = rows.map(
    (row) => `${row.date},${row.memberId},${row.projectId},${formatHours(row.hours)}`,
  );
  return [header, ...lines].join("\n") + "\n";
}

export function sumHours(rows: readonly ReportRow[]): number {
  return roundHours(rows.reduce((sum, row) => sum + row.hours, 0));
}

/** UTF-8 でのバイト数。Buffer を使わないのでブラウザ環境でも同じ結果になります */
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

/** "6" / "7.5" のように、Python 版と同じ文字列にする */
function formatHours(hours: number): string {
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
}

function roundHours(hours: number): number {
  return Math.round(hours * 10) / 10;
}
