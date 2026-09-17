/**
 * 社内申請ワークフローのドメイン層
 *
 * このファイルは MCP を知りません（SDK も zod も import しません）。
 * セッション10 の data.ts を土台に、最終プロジェクト用に 3 点を足しています。
 *   ① 初期データを 24 件にした（一括検索を 8 チャンクに分けるため）
 *   ② previewToken を HMAC 署名つきにした
 *   ③ 失敗を DomainFailure（code / what / next）で表し、MCP 層がそのまま使えるようにした
 */
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const CATEGORIES = ["expense", "purchase", "leave", "travel"] as const;
export type Category = (typeof CATEGORIES)[number];

export const STATUSES = ["draft", "in_review", "approved", "rejected"] as const;
export type Status = (typeof STATUSES)[number];

export const DECISIONS = ["approve", "reject", "return_for_changes"] as const;
export type Decision = (typeof DECISIONS)[number];

export const DETAIL_SECTIONS = ["comments", "attachments", "history"] as const;
export type DetailSection = (typeof DETAIL_SECTIONS)[number];

/** 一括検索を分割する数。進捗通知の total になります */
export const SCAN_CHUNKS = 8;

export const CATEGORY_LABEL: Readonly<Record<Category, string>> = {
  expense: "経費精算",
  purchase: "物品購入",
  leave: "休暇",
  travel: "出張",
};

/** 返す量の上限。AI の指定に任せず、サーバーが決めます */
export const BUDGET = { listChars: 1_200, bodyChars: 400, sectionItems: 5 } as const;

export type ApprovalStep = {
  order: number;
  approverId: string;
  approverName: string;
  state: "pending" | "approved" | "rejected";
  decidedAt: string | null;
};

export type Comment = { id: string; authorId: string; body: string; postedAt: string };
export type Attachment = { id: string; fileName: string; sizeBytes: number; uri: string };
export type HistoryEntry = { at: string; actorId: string; action: string; note: string };

export type WorkflowRequest = {
  id: string;
  title: string;
  category: Category;
  amountYen: number;
  applicantId: string;
  applicantName: string;
  department: string;
  status: Status;
  body: string;
  createdAt: string;
  updatedAt: string;
  approvals: ApprovalStep[];
  comments: Comment[];
  attachments: Attachment[];
  history: HistoryEntry[];
};

export type Store = {
  requests: Map<string, WorkflowRequest>;
  nextNumber: number;
  /** 決定的な時刻。呼ぶたびに 1 分進む */
  now: () => string;
  /** previewToken の署名鍵。プロセスの外へ出しません */
  previewSecret: Buffer;
};

/**
 * ドメイン層の失敗。
 * code / what / next の 3 つを持たせておくと、MCP 層は retryable を足すだけで
 * セッション11 の 3 要素の文面が作れます（文面の作り方を 1 か所に閉じ込められる）。
 */
export type DomainFailure = {
  readonly ok: false;
  readonly code: "not_found" | "invalid_state" | "invalid_argument";
  readonly what: string;
  readonly next: string;
};

const HIGH_AMOUNT_THRESHOLD = 50_000;
const BASE_TIME = Date.UTC(2026, 7, 20, 9, 0, 0);

const APPLICANTS = [
  { id: "u-001", name: "佐藤 花子", department: "営業部" },
  { id: "u-002", name: "鈴木 一郎", department: "開発部" },
  { id: "u-003", name: "田中 実", department: "開発部" },
] as const;

/** 金額で承認段数が変わる。段数の計算はここ 1 か所だけ */
function approvalRoute(amountYen: number): ApprovalStep[] {
  const route: ApprovalStep[] = [
    { order: 1, approverId: "u-900", approverName: "山田 課長", state: "pending", decidedAt: null },
  ];
  if (amountYen >= HIGH_AMOUNT_THRESHOLD) {
    route.push({
      order: 2,
      approverId: "u-901",
      approverName: "高橋 部長",
      state: "pending",
      decidedAt: null,
    });
  }
  return route;
}

type GeneratedSeed = {
  category: Category;
  status: Status;
  applicant: 0 | 1 | 2;
  amountYen: number;
};

/** 後半 19 件。表で持つと「in_review が何件か」を目で数えられます（受け入れ条件の検算に使う） */
const GENERATED: readonly GeneratedSeed[] = [
  { category: "expense", status: "approved", applicant: 0, amountYen: 15_000 },
  { category: "purchase", status: "in_review", applicant: 1, amountYen: 31_000 },
  { category: "leave", status: "approved", applicant: 2, amountYen: 0 },
  { category: "travel", status: "draft", applicant: 0, amountYen: 52_000 },
  { category: "expense", status: "rejected", applicant: 1, amountYen: 8_000 },
  { category: "purchase", status: "approved", applicant: 2, amountYen: 120_000 },
  { category: "leave", status: "in_review", applicant: 0, amountYen: 0 },
  { category: "travel", status: "approved", applicant: 1, amountYen: 76_000 },
  { category: "expense", status: "draft", applicant: 2, amountYen: 4_300 },
  { category: "purchase", status: "in_review", applicant: 0, amountYen: 28_000 },
  { category: "leave", status: "approved", applicant: 1, amountYen: 0 },
  { category: "travel", status: "rejected", applicant: 2, amountYen: 91_000 },
  { category: "expense", status: "approved", applicant: 0, amountYen: 6_700 },
  { category: "purchase", status: "draft", applicant: 1, amountYen: 45_000 },
  { category: "leave", status: "approved", applicant: 2, amountYen: 0 },
  { category: "travel", status: "in_review", applicant: 0, amountYen: 33_000 },
  { category: "expense", status: "approved", applicant: 1, amountYen: 9_800 },
  { category: "purchase", status: "rejected", applicant: 2, amountYen: 150_000 },
  { category: "travel", status: "draft", applicant: 0, amountYen: 64_000 },
];

function baseSeed(): WorkflowRequest[] {
  return [
    {
      id: "req-1001",
      title: "8月分の交通費精算",
      category: "expense",
      amountYen: 12_480,
      applicantId: "u-001",
      applicantName: "佐藤 花子",
      department: "営業部",
      status: "draft",
      body: "8月の顧客訪問 6 件分の交通費です。内訳は経路ごとに記載しました。",
      createdAt: "2026-08-18T09:00:00.000Z",
      updatedAt: "2026-08-18T09:10:00.000Z",
      approvals: approvalRoute(12_480),
      comments: [],
      attachments: [],
      history: [{ at: "2026-08-18T09:00:00.000Z", actorId: "u-001", action: "created", note: "" }],
    },
    {
      id: "req-1002",
      title: "モニター 2 台の購入",
      category: "purchase",
      amountYen: 64_800,
      applicantId: "u-002",
      applicantName: "鈴木 一郎",
      department: "開発部",
      status: "in_review",
      body: "開発用の 27 インチモニターを 2 台購入したいです。既存機は 5 年以上経過しています。",
      createdAt: "2026-08-17T01:00:00.000Z",
      updatedAt: "2026-08-17T02:00:00.000Z",
      approvals: approvalRoute(64_800),
      comments: [],
      attachments: [],
      history: [
        { at: "2026-08-17T01:00:00.000Z", actorId: "u-002", action: "created", note: "" },
        { at: "2026-08-17T02:00:00.000Z", actorId: "u-002", action: "submitted", note: "" },
      ],
    },
    {
      id: "req-1003",
      title: "外部研修の参加費",
      category: "expense",
      amountYen: 88_000,
      applicantId: "u-001",
      applicantName: "佐藤 花子",
      department: "営業部",
      status: "in_review",
      body: "提案力強化の外部研修（2 日間）への参加費です。受講後に社内へ共有会を実施します。",
      createdAt: "2026-08-18T10:00:00.000Z",
      updatedAt: "2026-08-18T12:00:00.000Z",
      approvals: approvalRoute(88_000),
      comments: [
        { id: "c-01", authorId: "u-900", body: "見積書を添付してください。", postedAt: "2026-08-18T11:00:00.000Z" },
        { id: "c-02", authorId: "u-001", body: "添付しました。ご確認ください。", postedAt: "2026-08-18T12:00:00.000Z" },
      ],
      attachments: [
        { id: "a-01", fileName: "estimate.pdf", sizeBytes: 84_213, uri: "https://intra.example.com/files/a-01" },
      ],
      history: [
        { at: "2026-08-18T10:00:00.000Z", actorId: "u-001", action: "created", note: "" },
        { at: "2026-08-18T10:30:00.000Z", actorId: "u-001", action: "submitted", note: "" },
        { at: "2026-08-18T12:00:00.000Z", actorId: "u-001", action: "commented", note: "" },
      ],
    },
    {
      id: "req-1004",
      title: "夏季休暇（3日間）",
      category: "leave",
      amountYen: 0,
      applicantId: "u-003",
      applicantName: "田中 実",
      department: "開発部",
      status: "approved",
      body: "8月26日から28日まで夏季休暇を取得します。",
      createdAt: "2026-08-10T00:00:00.000Z",
      updatedAt: "2026-08-11T00:00:00.000Z",
      approvals: [
        { order: 1, approverId: "u-900", approverName: "山田 課長", state: "approved", decidedAt: "2026-08-11T00:00:00.000Z" },
      ],
      comments: [],
      attachments: [],
      history: [
        { at: "2026-08-10T00:00:00.000Z", actorId: "u-003", action: "created", note: "" },
        { at: "2026-08-11T00:00:00.000Z", actorId: "u-900", action: "approved", note: "" },
      ],
    },
    {
      id: "req-1005",
      title: "大阪出張の旅費概算",
      category: "travel",
      amountYen: 43_200,
      applicantId: "u-002",
      applicantName: "鈴木 一郎",
      department: "開発部",
      status: "rejected",
      body: "9月の展示会視察に伴う出張旅費の概算です。",
      createdAt: "2026-08-12T00:00:00.000Z",
      updatedAt: "2026-08-13T00:00:00.000Z",
      approvals: [
        { order: 1, approverId: "u-900", approverName: "山田 課長", state: "rejected", decidedAt: "2026-08-13T00:00:00.000Z" },
      ],
      comments: [],
      attachments: [],
      history: [
        { at: "2026-08-12T00:00:00.000Z", actorId: "u-002", action: "created", note: "" },
        { at: "2026-08-13T00:00:00.000Z", actorId: "u-900", action: "rejected", note: "予算超過" },
      ],
    },
  ];
}

export function createStore(): Store {
  let tick = 0;
  const now = (): string => new Date(BASE_TIME + tick++ * 60_000).toISOString();

  const seed = baseSeed();
  for (const [index, entry] of GENERATED.entries()) {
    const id = `req-${1006 + index}`;
    // APPLICANTS はタプルなので、0|1|2 で引けば必ず値が取れる（noUncheckedIndexedAccess でも安全）
    const applicant = APPLICANTS[entry.applicant];
    const label = CATEGORY_LABEL[entry.category];
    const day = String(10 + index).padStart(2, "0");
    const createdAt = `2026-07-${day}T00:00:00.000Z`;
    const updatedAt = `2026-07-${day}T06:00:00.000Z`;
    seed.push({
      id,
      title: `${label}の申請（${id}）`,
      category: entry.category,
      amountYen: entry.amountYen,
      applicantId: applicant.id,
      applicantName: applicant.name,
      department: applicant.department,
      status: entry.status,
      body: `${label}に関する申請です。金額は ${entry.amountYen} 円で、部門長の確認を受けています。`,
      createdAt,
      updatedAt,
      approvals: approvalRoute(entry.amountYen),
      comments: [],
      attachments: [],
      history: [{ at: createdAt, actorId: applicant.id, action: "created", note: "" }],
    });
  }

  return {
    requests: new Map(seed.map((request) => [request.id, request])),
    nextNumber: 1006 + GENERATED.length,
    now,
    previewSecret: randomBytes(32),
  };
}

// ---------------------------------------------------------------------------
// 検索（チャンク走査つき）
// ---------------------------------------------------------------------------

export type RequestSummary = {
  id: string;
  title: string;
  category: string;
  status: string;
  amountYen: number;
  applicantName: string;
  updatedAt: string;
};

export type SearchParams = {
  query?: string;
  status?: readonly Status[];
  category?: Category;
  applicantId?: string;
  minAmountYen?: number;
  limit: number;
  cursor?: string;
};

export type SearchResult = {
  total: number;
  returned: number;
  hasMore: boolean;
  nextCursor?: string;
  items: RequestSummary[];
};

export function sortedRequests(store: Store): WorkflowRequest[] {
  return [...store.requests.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** 走査対象を SCAN_CHUNKS 個に等分する。幅を先に決めるので取りこぼしが出ない */
export function chunkOf(store: Store, index: number): WorkflowRequest[] {
  const all = sortedRequests(store);
  const width = Math.ceil(all.length / SCAN_CHUNKS);
  return all.slice(index * width, (index + 1) * width);
}

export function filterChunk(
  rows: readonly WorkflowRequest[],
  params: SearchParams,
): WorkflowRequest[] {
  return rows.filter((request) => {
    if (params.query !== undefined) {
      const needle = params.query.toLowerCase();
      if (!`${request.title}\n${request.body}`.toLowerCase().includes(needle)) return false;
    }
    if (params.status !== undefined && params.status.length > 0) {
      if (!params.status.includes(request.status)) return false;
    }
    if (params.category !== undefined && request.category !== params.category) return false;
    if (params.applicantId !== undefined && request.applicantId !== params.applicantId) return false;
    if (params.minAmountYen !== undefined && request.amountYen < params.minAmountYen) return false;
    return true;
  });
}

/** カーソルは不透明。中身の意味はサーバーだけが知る */
export function encodeCursor(afterId: string): string {
  return Buffer.from(JSON.stringify({ v: 1, afterId }), "utf8").toString("base64url");
}

function decodeCursor(cursor: string): string | undefined {
  try {
    const parsed: unknown = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
    if (typeof parsed !== "object" || parsed === null) return undefined;
    const record = parsed as { v?: unknown; afterId?: unknown };
    if (record.v !== 1 || typeof record.afterId !== "string") return undefined;
    return record.afterId;
  } catch {
    return undefined;
  }
}

function toSummary(request: WorkflowRequest): RequestSummary {
  return {
    id: request.id,
    title: request.title,
    category: request.category,
    status: request.status,
    amountYen: request.amountYen,
    applicantName: request.applicantName,
    updatedAt: request.updatedAt,
  };
}

export type SearchOutcome = { ok: true; result: SearchResult } | DomainFailure;

export function finalizePage(
  matched: readonly WorkflowRequest[],
  params: SearchParams,
): SearchOutcome {
  let rest = matched;
  if (params.cursor !== undefined) {
    const afterId = decodeCursor(params.cursor);
    if (afterId === undefined) {
      return {
        ok: false,
        code: "invalid_argument",
        what: "cursor の形式が不正です。",
        next: "前回の結果に含まれていた nextCursor をそのまま渡してください。先頭から取り直すなら cursor を省略します。",
      };
    }
    rest = matched.filter((request) => request.id > afterId);
  }
  const page = rest.slice(0, params.limit);
  const hasMore = rest.length > page.length;
  const last = page.at(-1);
  return {
    ok: true,
    result: {
      total: matched.length,
      returned: page.length,
      hasMore,
      ...(hasMore && last !== undefined ? { nextCursor: encodeCursor(last.id) } : {}),
      items: page.map(toSummary),
    },
  };
}

export function formatSummaryLine(item: RequestSummary): string {
  return `- ${item.id} ${item.title}（${item.category} / ${item.amountYen} 円 / ${item.status} / 申請者 ${item.applicantName}）`;
}

/** 行を上限まで詰め、切ったことと次の一手を書き添える。黙って切るのが最悪 */
export function fitLines(lines: readonly string[], maxChars: number, hint: string): string {
  const kept: string[] = [];
  let used = 0;
  for (const line of lines) {
    if (used + line.length + 1 > maxChars) break;
    kept.push(line);
    used += line.length + 1;
  }
  const omitted = lines.length - kept.length;
  if (omitted > 0) {
    kept.push(`…（返却上限 ${maxChars} 文字に達したため ${omitted} 件を省略しました。${hint}）`);
  }
  return kept.join("\n");
}

export function fitBody(request: WorkflowRequest): string {
  if (request.body.length <= BUDGET.bodyChars) return request.body;
  return (
    `${request.body.slice(0, BUDGET.bodyChars)}…\n` +
    `（本文は ${request.body.length} 文字あるため先頭 ${BUDGET.bodyChars} 文字だけを返しました。` +
    `全文はリソース request://${request.id} を読んでください）`
  );
}

function tailSection(label: string, items: readonly string[]): string[] {
  const shown = items.slice(-BUDGET.sectionItems);
  const suffix = items.length > shown.length ? `のうち直近 ${shown.length} 件` : "";
  return [`${label}（全 ${items.length} 件${suffix}）:`, ...shown];
}

export function formatDetailText(
  request: WorkflowRequest,
  include: readonly DetailSection[],
): string {
  const lines = [
    `${request.id} ${request.title}`,
    `区分: ${request.category} / 金額: ${request.amountYen} 円 / 状態: ${request.status}`,
    `申請者: ${request.applicantName}（${request.applicantId} / ${request.department}）`,
    `更新: ${request.updatedAt}`,
    "本文:",
    fitBody(request),
    "承認ルート:",
    ...request.approvals.map((step) => `- ${step.order}. ${step.approverName}: ${step.state}`),
  ];
  if (include.includes("comments")) {
    lines.push(...tailSection("コメント", request.comments.map((c) => `- ${c.authorId}: ${c.body}`)));
  }
  if (include.includes("attachments")) {
    lines.push(
      ...tailSection("添付", request.attachments.map((a) => `- ${a.fileName}（${a.sizeBytes} bytes）`)),
    );
  }
  if (include.includes("history")) {
    lines.push(
      ...tailSection("履歴", request.history.map((h) => `- ${h.at} ${h.actorId} ${h.action}`)),
    );
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// previewToken（HMAC 署名つき）
// ---------------------------------------------------------------------------

export type PreviewPayload = {
  v: 2;
  action: "submit" | "decide";
  requestId: string;
  updatedAt: string;
  decision?: Decision;
  comment?: string;
};

export function makePreviewToken(secret: Buffer, payload: PreviewPayload): string {
  const body = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  const signature = createHmac("sha256", secret).update(body).digest("base64url");
  return `${body}.${signature}`;
}

/** 期待するトークンを作り直して定数時間で比べる。長さが違えば例外になるので先に弾く */
export function verifyPreviewToken(
  secret: Buffer,
  token: string,
  expected: PreviewPayload,
): boolean {
  const want = Buffer.from(makePreviewToken(secret, expected), "utf8");
  const got = Buffer.from(token, "utf8");
  if (want.length !== got.length) return false;
  return timingSafeEqual(want, got);
}

// ---------------------------------------------------------------------------
// 起票・更新
// ---------------------------------------------------------------------------

export type SaveInput = {
  requestId?: string;
  title?: string;
  category?: Category;
  amountYen?: number;
  body?: string;
};

export type SaveOutcome =
  | { ok: true; created: boolean; request: WorkflowRequest }
  | DomainFailure;

export function saveRequest(store: Store, input: SaveInput): SaveOutcome {
  if (input.requestId === undefined) {
    // 条件付き必須は JSON Schema で表しづらいので、ここで「何が足りないか」を列挙する
    const missing = (["title", "category", "amountYen", "body"] as const).filter(
      (key) => input[key] === undefined,
    );
    if (missing.length > 0) {
      return {
        ok: false,
        code: "invalid_argument",
        what: `新規作成には ${missing.join(", ")} が足りません。`,
        next: "不足している引数を付けて save_request を呼び直してください。既存の下書きを更新したい場合は requestId を指定します。",
      };
    }
    const id = `req-${store.nextNumber++}`;
    const at = store.now();
    const amountYen = input.amountYen ?? 0;
    const request: WorkflowRequest = {
      id,
      title: input.title ?? "",
      category: input.category ?? "expense",
      amountYen,
      applicantId: "u-001",
      applicantName: "佐藤 花子",
      department: "営業部",
      status: "draft",
      body: input.body ?? "",
      createdAt: at,
      updatedAt: at,
      approvals: approvalRoute(amountYen),
      comments: [],
      attachments: [],
      history: [{ at, actorId: "u-001", action: "created", note: "" }],
    };
    store.requests.set(id, request);
    return { ok: true, created: true, request };
  }

  const request = store.requests.get(input.requestId);
  if (request === undefined) return notFound(input.requestId);
  if (request.status !== "draft") {
    return {
      ok: false,
      code: "invalid_state",
      what: `申請 ${request.id} は ${request.status} のため編集できません。`,
      next: "編集できるのは draft の申請だけです。get_request で状態を確認してください。",
    };
  }

  if (input.title !== undefined) request.title = input.title;
  if (input.category !== undefined) request.category = input.category;
  if (input.body !== undefined) request.body = input.body;
  if (input.amountYen !== undefined) {
    request.amountYen = input.amountYen;
    request.approvals = approvalRoute(input.amountYen);
  }
  request.updatedAt = store.now();
  request.history.push({ at: request.updatedAt, actorId: "u-001", action: "updated", note: "" });
  return { ok: true, created: false, request };
}

function notFound(requestId: string): DomainFailure {
  return {
    ok: false,
    code: "not_found",
    what: `申請 ${requestId} は見つかりません。`,
    next: "search_requests で ID を確認してから呼び直してください。",
  };
}

// ---------------------------------------------------------------------------
// 二段階操作
// ---------------------------------------------------------------------------

export type SubmitPreview = {
  ok: true;
  requestId: string;
  currentStatus: Status;
  nextStatus: Status;
  notifyTo: string[];
  previewToken: string;
};

export function previewSubmit(store: Store, requestId: string): SubmitPreview | DomainFailure {
  const request = store.requests.get(requestId);
  if (request === undefined) return notFound(requestId);
  if (request.status !== "draft") {
    return {
      ok: false,
      code: "invalid_state",
      what: `申請 ${requestId} は ${request.status} のため提出できません。`,
      next: "提出できるのは draft の申請だけです。すでに審査中なら decide_request を使ってください。",
    };
  }
  const firstApprover = request.approvals.find((step) => step.state === "pending");
  return {
    ok: true,
    requestId,
    currentStatus: request.status,
    nextStatus: "in_review",
    notifyTo: firstApprover === undefined ? [] : [firstApprover.approverName],
    previewToken: makePreviewToken(store.previewSecret, {
      v: 2,
      action: "submit",
      requestId,
      updatedAt: request.updatedAt,
    }),
  };
}

export function applySubmit(
  store: Store,
  requestId: string,
): { ok: true; status: Status; notifyTo: string[] } | DomainFailure {
  const preview = previewSubmit(store, requestId);
  if (!preview.ok) return preview;
  const request = store.requests.get(requestId);
  if (request === undefined) return notFound(requestId);
  request.status = "in_review";
  request.updatedAt = store.now();
  request.history.push({
    at: request.updatedAt,
    actorId: request.applicantId,
    action: "submitted",
    note: "",
  });
  return { ok: true, status: request.status, notifyTo: preview.notifyTo };
}

export type DecisionPreview = {
  ok: true;
  requestId: string;
  decision: Decision;
  currentStatus: Status;
  nextStatus: Status;
  stepLabel: string;
  finalizes: boolean;
  notifyTo: string[];
  previewToken: string;
};

export function previewDecision(
  store: Store,
  requestId: string,
  decision: Decision,
  comment?: string,
): DecisionPreview | DomainFailure {
  const request = store.requests.get(requestId);
  if (request === undefined) return notFound(requestId);
  if (request.status !== "in_review") {
    return {
      ok: false,
      code: "invalid_state",
      what: `申請 ${requestId} は ${request.status} のため決裁できません。`,
      next: "決裁できるのは in_review の申請だけです。draft なら申請者に submit_request を依頼してください。",
    };
  }
  if (decision !== "approve" && (comment === undefined || comment.trim() === "")) {
    return {
      ok: false,
      code: "invalid_argument",
      what: `decision="${decision}" では comment（理由）が必須です。`,
      next: "申請者に伝わる理由を 1 文以上で comment に指定して呼び直してください。",
    };
  }

  const pending = request.approvals.filter((step) => step.state === "pending");
  const current = pending[0];
  if (current === undefined) {
    return {
      ok: false,
      code: "invalid_state",
      what: `申請 ${requestId} に未処理の承認ステップがありません。`,
      next: "get_request で承認ルートの状態を確認してください。",
    };
  }
  const isLastStep = pending.length === 1;
  const nextStatus: Status =
    decision === "reject"
      ? "rejected"
      : decision === "return_for_changes"
        ? "draft"
        : isLastStep
          ? "approved"
          : "in_review";
  const notifyTo =
    decision === "approve" && !isLastStep
      ? [pending[1]?.approverName ?? request.applicantName]
      : [request.applicantName];

  return {
    ok: true,
    requestId,
    decision,
    currentStatus: request.status,
    nextStatus,
    stepLabel: `${current.order}/${request.approvals.length} 段目`,
    finalizes: nextStatus !== "in_review",
    notifyTo,
    previewToken: makePreviewToken(store.previewSecret, {
      v: 2,
      action: "decide",
      requestId,
      updatedAt: request.updatedAt,
      decision,
      ...(comment === undefined ? {} : { comment }),
    }),
  };
}

export function applyDecision(
  store: Store,
  requestId: string,
  decision: Decision,
  comment?: string,
): { ok: true; status: Status; stepLabel: string; finalizes: boolean } | DomainFailure {
  const preview = previewDecision(store, requestId, decision, comment);
  if (!preview.ok) return preview;
  const request = store.requests.get(requestId);
  if (request === undefined) return notFound(requestId);
  const current = request.approvals.find((step) => step.state === "pending");
  const at = store.now();

  if (current !== undefined && decision === "approve") {
    current.state = "approved";
    current.decidedAt = at;
  } else if (current !== undefined && decision === "reject") {
    current.state = "rejected";
    current.decidedAt = at;
  } else if (decision === "return_for_changes") {
    request.approvals = approvalRoute(request.amountYen);
  }

  request.status = preview.nextStatus;
  request.updatedAt = at;
  request.history.push({
    at,
    actorId: current?.approverId ?? "u-900",
    action: decision,
    note: comment ?? "",
  });
  if (comment !== undefined && comment.trim() !== "") {
    request.comments.push({
      id: `c-${String(request.comments.length + 1).padStart(2, "0")}`,
      authorId: current?.approverId ?? "u-900",
      body: comment,
      postedAt: at,
    });
  }
  return {
    ok: true,
    status: request.status,
    stepLabel: preview.stepLabel,
    finalizes: preview.finalizes,
  };
}

export function addComment(
  store: Store,
  requestId: string,
  body: string,
  links: readonly string[],
): { ok: true; commentId: string; total: number } | DomainFailure {
  const request = store.requests.get(requestId);
  if (request === undefined) return notFound(requestId);
  const at = store.now();
  const commentId = `c-${String(request.comments.length + 1).padStart(2, "0")}`;
  const text = links.length === 0 ? body : `${body}\n参考: ${links.join(" ")}`;
  request.comments.push({ id: commentId, authorId: "u-900", body: text, postedAt: at });
  request.updatedAt = at;
  request.history.push({ at, actorId: "u-900", action: "commented", note: "" });
  return { ok: true, commentId, total: request.comments.length };
}

// ---------------------------------------------------------------------------
// リソース・プロンプト用
// ---------------------------------------------------------------------------

/** 補完。サーバー側で前方一致に絞る（全件返さない） */
export function completeRequestIds(store: Store, value: string): string[] {
  return sortedRequests(store)
    .map((request) => request.id)
    .filter((id) => id.startsWith(value))
    .slice(0, 20);
}

/** プロンプトの参考資料。同じ区分の承認済み申請を 1 件だけ選ぶ */
export function findReference(store: Store, category: Category): WorkflowRequest | undefined {
  return sortedRequests(store).find(
    (request) => request.category === category && request.status === "approved",
  );
}
