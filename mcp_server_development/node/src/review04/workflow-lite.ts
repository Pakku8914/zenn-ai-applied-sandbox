/**
 * 横断復習4 の共通題材 ―― 社内申請ワークフロー（ドメイン層の縮小版）
 *
 * MCP には依存しません。12 件の申請を決定的に生成します。
 * 失敗は message ではなく reason（コード）で返します
 * （文面を組み立てるのは MCP 層の責務、という分離をここでも守ります）。
 */
export const CATEGORIES = ["expense", "leave", "purchase"] as const;
export type Category = (typeof CATEGORIES)[number];

export const STATUSES = ["draft", "submitted", "approved", "rejected"] as const;
export type Status = (typeof STATUSES)[number];

export const DECISIONS = ["approve", "reject"] as const;
export type Decision = (typeof DECISIONS)[number];

export type WorkflowRequest = {
  id: string;
  title: string;
  category: Category;
  amountYen: number;
  applicantId: string;
  applicantName: string;
  status: Status;
  /** 申請理由。req-1003 だけ 900 文字前後（「返しすぎ」の題材） */
  reason: string;
  /** 決裁のたびに 1 増える。二段階の確定チェックに使う */
  version: number;
  updatedAt: string;
};

export type WorkflowStore = { requests: Map<string, WorkflowRequest> };

const CATEGORY_TITLES: Record<Category, string> = {
  expense: "経費の精算",
  leave: "休暇の申請",
  purchase: "備品の購入",
};
const NAMES = ["佐藤 花子", "鈴木 一郎", "田中 実"] as const;

/** 900 文字前後の申請理由を決定的に組み立てる */
function longReason(): string {
  const line =
    "現行の検証端末が保証期間を過ぎており、貸出機では負荷試験を再現できないため、購入を希望します。";
  return Array.from({ length: 18 }, (_, index) => `${index + 1}. ${line}`).join("\n");
}

export function createWorkflowStore(): WorkflowStore {
  const requests = new Map<string, WorkflowRequest>();
  for (let index = 0; index < 12; index++) {
    const id = `req-1${String(index + 1).padStart(3, "0")}`;
    const category = CATEGORIES[index % 3] as Category;
    // req-1001/1005/1009 が approved、req-1002/1006/1010 が rejected、残り 6 件が submitted
    const status: Status =
      index % 4 === 0 ? "approved" : index % 4 === 1 ? "rejected" : "submitted";
    requests.set(id, {
      id,
      title: `${CATEGORY_TITLES[category]}（${index + 1}）`,
      category,
      amountYen: category === "leave" ? 0 : (index + 1) * 12_000,
      applicantId: `u-00${(index % 3) + 1}`,
      applicantName: NAMES[index % 3] as string,
      status,
      reason: id === "req-1003" ? longReason() : `${CATEGORY_TITLES[category]}の申請です。`,
      version: 1,
      updatedAt: `2026-08-${String((index % 28) + 1).padStart(2, "0")}T09:00:00.000Z`,
    });
  }
  return { requests };
}

export type RequestSummary = {
  id: string;
  title: string;
  category: Category;
  amountYen: number;
  status: Status;
  applicantName: string;
};

export function toSummary(row: WorkflowRequest): RequestSummary {
  return {
    id: row.id,
    title: row.title,
    category: row.category,
    amountYen: row.amountYen,
    status: row.status,
    applicantName: row.applicantName,
  };
}

/** 一覧の 1 行。申請理由は含めない（一覧に本文を混ぜないための境界） */
export function summaryLine(item: RequestSummary): string {
  return `- ${item.id} ${item.title}（${item.category} / ${item.amountYen} 円 / ${item.status} / 申請者 ${item.applicantName}）`;
}

/** 申請 1 件への参照 URI。本文を運ばず参照だけを返すために使う */
export function toUri(id: string): string {
  return `request://${id}`;
}

export type SearchParams = {
  category?: Category;
  status?: readonly Status[];
  query?: string;
  limit: number;
};

export function searchRequests(
  store: WorkflowStore,
  params: SearchParams,
): { total: number; items: RequestSummary[] } {
  const all = [...store.requests.values()].sort((a, b) => (a.id < b.id ? -1 : 1));
  const matched = all.filter((row) => {
    if (params.category !== undefined && row.category !== params.category) return false;
    if (params.status !== undefined && params.status.length > 0) {
      if (!params.status.includes(row.status)) return false;
    }
    if (params.query !== undefined && params.query.length > 0) {
      const needle = params.query.toLowerCase();
      if (!`${row.title}\n${row.reason}`.toLowerCase().includes(needle)) return false;
    }
    return true;
  });
  return { total: matched.length, items: matched.slice(0, params.limit).map(toSummary) };
}

/** 決裁の結果。失敗の分類はドメイン層が持つ */
export type DecideOutcome =
  | { ok: true; status: Status; version: number }
  | { ok: false; reason: "not_found" }
  | { ok: false; reason: "not_decidable"; status: Status };

export function decideRequest(
  store: WorkflowStore,
  requestId: string,
  decision: Decision,
): DecideOutcome {
  const row = store.requests.get(requestId);
  if (row === undefined) return { ok: false, reason: "not_found" };
  if (row.status !== "submitted") return { ok: false, reason: "not_decidable", status: row.status };
  row.status = decision === "approve" ? "approved" : "rejected";
  row.version += 1;
  row.updatedAt = "2026-08-20T09:00:00.000Z";
  return { ok: true, status: row.status, version: row.version };
}
