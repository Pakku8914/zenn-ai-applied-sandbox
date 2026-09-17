/**
 * チーム稼働ダッシュボード ― データ層
 *
 * このファイルには MCP の要素が 1 つも出てきません。それが狙いです。
 * 「サーバーの中身」＝ドメインロジックを MCP から独立させておくと、
 * テスト・移植・機能追加のたびにプロトコル層を触らずに済みます。
 *
 * 実務では、ここが DB アクセスや社内 API 呼び出しに置き換わります。
 * 本章では学習のためインメモリの固定データを使います。
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
  /** YYYY-MM-DD 形式。この形式は文字列のまま辞書順で比較できるので日付ライブラリが不要です */
  readonly date: string;
  readonly hours: number;
};

/**
 * 集計できる期間の上限（日数）。
 * 上限を設けるのは「巨大な期間を指定されて処理が終わらない」事故を防ぐためです。
 * リソース枯渇対策の詳細はセッション15 で扱います。
 */
export const MAX_RANGE_DAYS = 92;

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

/** メンバー ID からメンバーを引く。見つからなければ undefined */
export function findMember(memberId: string): Member | undefined {
  return members.find((member) => member.id === memberId);
}

/**
 * メンバー一覧を返す。team を指定するとそのチームだけに絞る。
 * 並び順を ID の昇順で固定しているのは、呼び出すたびに順番が変わらないようにするためです
 * （順番が安定していないと、後のセッションで書くスナップショットテストが壊れます）。
 */
export function listMembers(team?: string): Member[] {
  const filtered = team === undefined ? [...members] : members.filter((member) => member.team === team);
  return filtered.sort((a, b) => a.id.localeCompare(b.id));
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

/**
 * 期間内の稼働時間をメンバー別に集計する。
 * from / to はどちらも「その日を含む」。稼働記録が 1 件もないメンバーは結果に含めない。
 */
export function summarizeHours(params: { from: string; to: string; memberId?: string }): HoursSummary {
  const { from, to, memberId } = params;

  const targets = workLogs.filter(
    (log) =>
      log.date >= from &&
      log.date <= to &&
      (memberId === undefined || log.memberId === memberId),
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

/**
 * from から to までの日数（両端を含む）。
 * 日付として解釈できない場合は NaN を返す。
 * UTC 固定で計算しているのは、サーバーが動く場所のタイムゾーンで結果が変わらないようにするためです。
 */
export function daysBetween(from: string, to: string): number {
  const fromMs = Date.parse(`${from}T00:00:00Z`);
  const toMs = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(fromMs) || Number.isNaN(toMs)) {
    return Number.NaN;
  }
  return Math.floor((toMs - fromMs) / 86_400_000) + 1;
}

/** 小数第 1 位に丸める。浮動小数点の誤差が表示に出るのを防ぐため */
function roundHours(hours: number): number {
  return Math.round(hours * 10) / 10;
}
