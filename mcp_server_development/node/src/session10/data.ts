/**
 * 社内申請ワークフローのデータ層
 *
 * MCP には一切依存しません（import が 1 つもないことに注目してください）。
 * 「REST API の向こう側にある業務ロジック」をここに閉じ込めることで、
 * ツール設計の議論と業務ロジックの実装を分けて考えられるようにしています。
 *
 * このファイルはセッション11（エラー設計）と最終プロジェクトでも使います。
 * データはメモリ上のみ。createStore() を呼ぶたびに同じ初期状態から始まります。
 */

/** 申請区分。マスタ参照ツールを作らず、入力スキーマの enum に埋め込む前提の固定リスト */
export const CATEGORIES = ["expense", "purchase", "leave", "travel"] as const;
export type Category = (typeof CATEGORIES)[number];

/** 申請の状態。差し戻しは draft に戻すので「差し戻し中」という状態は持たない */
export const STATUSES = ["draft", "in_review", "approved", "rejected"] as const;
export type Status = (typeof STATUSES)[number];

/** 決裁の種類。承認・却下・差し戻しを 1 つのツールにまとめるための列挙 */
export const DECISIONS = ["approve", "reject", "return_for_changes"] as const;
export type Decision = (typeof DECISIONS)[number];

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
  /** 次に払い出す申請番号 */
  nextNumber: number;
  /** 決定的な時刻。呼ぶたびに 1 分進む（何度実行しても同じ出力になるようにするため） */
  now: () => string;
};

/** 失敗を表す共通の形。メッセージの作り方はセッション11 で作り込みます */
export type Failure = { ok: false; message: string };

const BASE_TIME = Date.UTC(2026, 7, 20, 9, 0, 0);
const HIGH_AMOUNT_THRESHOLD = 50_000;

/** 金額で承認段数が変わる（5 万円以上は課長 → 部長の 2 段階） */
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

export function createStore(): Store {
  let tick = 0;
  const now = (): string => new Date(BASE_TIME + tick++ * 60_000).toISOString();

  const seed: WorkflowRequest[] = [
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
        {
          id: "c-01",
          authorId: "u-900",
          body: "見積書を添付してください。",
          postedAt: "2026-08-18T11:00:00.000Z",
        },
        {
          id: "c-02",
          authorId: "u-001",
          body: "添付しました。ご確認ください。",
          postedAt: "2026-08-18T12:00:00.000Z",
        },
      ],
      attachments: [
        {
          id: "a-01",
          fileName: "estimate.pdf",
          sizeBytes: 84_213,
          uri: "https://intra.example.com/files/a-01",
        },
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
        {
          order: 1,
          approverId: "u-900",
          approverName: "山田 課長",
          state: "approved",
          decidedAt: "2026-08-11T00:00:00.000Z",
        },
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
        {
          order: 1,
          approverId: "u-900",
          approverName: "山田 課長",
          state: "rejected",
          decidedAt: "2026-08-13T00:00:00.000Z",
        },
      ],
      comments: [],
      attachments: [],
      history: [
        { at: "2026-08-12T00:00:00.000Z", actorId: "u-002", action: "created", note: "" },
        { at: "2026-08-13T00:00:00.000Z", actorId: "u-900", action: "rejected", note: "予算超過" },
      ],
    },
  ];

  return {
    requests: new Map(seed.map((request) => [request.id, request])),
    nextNumber: 1006,
    now,
  };
}

// ---------------------------------------------------------------------------
// 検索
// ---------------------------------------------------------------------------

/** 一覧に載せる要約。本文（body）を含めないのがトークン効率の要点です */
export type RequestSummary = {
  id: string;
  title: string;
  category: Category;
  status: Status;
  amountYen: number;
  applicantName: string;
  updatedAt: string;
};

export type SearchResult = {
  total: number;
  returned: number;
  hasMore: boolean;
  nextCursor?: string;
  items: RequestSummary[];
};

export type SearchParams = {
  query?: string;
  status?: Status[];
  category?: Category;
  applicantId?: string;
  minAmountYen?: number;
  limit: number;
  cursor?: string;
};

/** カーソルを不透明な文字列にする（中身の意味はサーバーだけが知る／セッション8 と同じ方針） */
export function encodeCursor(afterId: string): string {
  return Buffer.from(JSON.stringify({ v: 1, afterId }), "utf8").toString("base64url");
}

export function decodeCursor(cursor: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw new Error(
      "cursor が不正です。前回の結果に含まれていた nextCursor の値をそのまま渡してください。",
    );
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    (parsed as { v?: unknown }).v !== 1 ||
    typeof (parsed as { afterId?: unknown }).afterId !== "string"
  ) {
    throw new Error("cursor の形式が不正です。cursor を省略して最初から取得し直してください。");
  }
  return (parsed as { afterId: string }).afterId;
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

export function searchRequests(store: Store, params: SearchParams): SearchResult {
  // ID 昇順で安定ソート。カーソルが安定して機能する前提条件です（セッション8）
  const all = [...store.requests.values()].sort((a, b) => (a.id < b.id ? -1 : 1));

  const matched = all.filter((request) => {
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

  const afterId = params.cursor === undefined ? undefined : decodeCursor(params.cursor);
  const rest = afterId === undefined ? matched : matched.filter((r) => r.id > afterId);
  const page = rest.slice(0, params.limit);
  const hasMore = rest.length > page.length;
  const last = page.at(-1);

  return {
    total: matched.length,
    returned: page.length,
    hasMore,
    ...(hasMore && last !== undefined ? { nextCursor: encodeCursor(last.id) } : {}),
    items: page.map(toSummary),
  };
}

/** 1 件を 1 行に収める。AI が読むのに十分で、かつ短い形を選びます */
export function formatSummaryLine(item: RequestSummary): string {
  return `- ${item.id} ${item.title}（${item.category} / ${item.amountYen} 円 / ${item.status} / 申請者 ${item.applicantName}）`;
}

// ---------------------------------------------------------------------------
// 詳細
// ---------------------------------------------------------------------------

export type DetailSection = "comments" | "attachments" | "history";

export type RequestDetail = {
  request: WorkflowRequest;
  include: DetailSection[];
};

export function getRequestDetail(
  store: Store,
  requestId: string,
  include: DetailSection[],
): RequestDetail | undefined {
  const request = store.requests.get(requestId);
  if (request === undefined) return undefined;
  return { request, include };
}

export function formatDetailText(detail: RequestDetail): string {
  const r = detail.request;
  const lines = [
    `${r.id} ${r.title}`,
    `区分: ${r.category} / 金額: ${r.amountYen} 円 / 状態: ${r.status}`,
    `申請者: ${r.applicantName}（${r.applicantId} / ${r.department}）`,
    `更新: ${r.updatedAt}`,
    "本文:",
    r.body,
    "承認ルート:",
    ...r.approvals.map(
      (step) => `- ${step.order}. ${step.approverName}（${step.approverId}）: ${step.state}`,
    ),
  ];

  if (detail.include.includes("comments")) {
    lines.push(`コメント（${r.comments.length} 件）:`);
    lines.push(...r.comments.map((c) => `- ${c.authorId} ${c.postedAt}: ${c.body}`));
  }
  if (detail.include.includes("attachments")) {
    lines.push(`添付（${r.attachments.length} 件）:`);
    lines.push(...r.attachments.map((a) => `- ${a.fileName}（${a.sizeBytes} bytes）${a.uri}`));
  }
  if (detail.include.includes("history")) {
    lines.push(`履歴（${r.history.length} 件）:`);
    lines.push(...r.history.map((h) => `- ${h.at} ${h.actorId} ${h.action} ${h.note}`.trimEnd()));
  }
  return lines.join("\n");
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

export type SaveOutcome = { ok: true; created: boolean; request: WorkflowRequest } | Failure;

export function saveRequest(store: Store, input: SaveInput): SaveOutcome {
  if (input.requestId === undefined) {
    // 新規作成。条件付き必須は JSON Schema で表現しづらいのでここで検査します
    const missing = (["title", "category", "amountYen", "body"] as const).filter(
      (key) => input[key] === undefined,
    );
    if (missing.length > 0) {
      return {
        ok: false,
        message: `新規作成には ${missing.join(", ")} が必要です。既存の下書きを更新したい場合は requestId を指定してください。`,
      };
    }
    const id = `req-${store.nextNumber++}`;
    const at = store.now();
    const request: WorkflowRequest = {
      id,
      title: input.title as string,
      category: input.category as Category,
      amountYen: input.amountYen as number,
      applicantId: "u-001",
      applicantName: "佐藤 花子",
      department: "営業部",
      status: "draft",
      body: input.body as string,
      createdAt: at,
      updatedAt: at,
      approvals: approvalRoute(input.amountYen as number),
      comments: [],
      attachments: [],
      history: [{ at, actorId: "u-001", action: "created", note: "" }],
    };
    store.requests.set(id, request);
    return { ok: true, created: true, request };
  }

  const request = store.requests.get(input.requestId);
  if (request === undefined) {
    return {
      ok: false,
      message: `申請 ${input.requestId} は見つかりません。search_requests で ID を確認してください。`,
    };
  }
  if (request.status !== "draft") {
    return {
      ok: false,
      message: `申請 ${request.id} は ${request.status} のため編集できません。編集できるのは draft の申請だけです。`,
    };
  }

  if (input.title !== undefined) request.title = input.title;
  if (input.category !== undefined) request.category = input.category;
  if (input.body !== undefined) request.body = input.body;
  if (input.amountYen !== undefined) {
    request.amountYen = input.amountYen;
    // 金額が変われば承認ルートも変わる。サーバー側で持つべき知識の代表例です
    request.approvals = approvalRoute(input.amountYen);
  }
  request.updatedAt = store.now();
  request.history.push({ at: request.updatedAt, actorId: "u-001", action: "updated", note: "" });
  return { ok: true, created: false, request };
}

// ---------------------------------------------------------------------------
// 二段階操作（プレビュー → 確定）
// ---------------------------------------------------------------------------

/**
 * ドライランの結果と確定操作を結びつける識別子。
 *
 * 申請の updatedAt を含めているため、プレビュー後に申請が変わっていれば
 * トークンが一致せず、確定が拒否されます（楽観的排他制御）。
 * これは「意図の一致」を確認する仕組みで、認可の代わりではありません（認可はセッション12）。
 */
export function makePreviewToken(input: {
  action: "submit" | "decide";
  requestId: string;
  updatedAt: string;
  decision?: Decision;
  comment?: string;
}): string {
  return Buffer.from(JSON.stringify({ v: 1, ...input }), "utf8").toString("base64url");
}

export type SubmitPreview = {
  ok: true;
  requestId: string;
  currentStatus: Status;
  nextStatus: Status;
  notifyTo: string[];
  previewToken: string;
};

export function previewSubmit(store: Store, requestId: string): SubmitPreview | Failure {
  const request = store.requests.get(requestId);
  if (request === undefined) {
    return { ok: false, message: `申請 ${requestId} は見つかりません。` };
  }
  if (request.status !== "draft") {
    return {
      ok: false,
      message: `申請 ${requestId} は ${request.status} のため提出できません。提出できるのは draft の申請だけです。`,
    };
  }
  const firstApprover = request.approvals.find((step) => step.state === "pending");
  return {
    ok: true,
    requestId,
    currentStatus: request.status,
    nextStatus: "in_review",
    notifyTo: firstApprover === undefined ? [] : [firstApprover.approverName],
    previewToken: makePreviewToken({
      action: "submit",
      requestId,
      updatedAt: request.updatedAt,
    }),
  };
}

export function applySubmit(
  store: Store,
  requestId: string,
): { ok: true; status: Status; notifyTo: string[] } | Failure {
  const preview = previewSubmit(store, requestId);
  if (!preview.ok) return preview;
  const request = store.requests.get(requestId) as WorkflowRequest;
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
): DecisionPreview | Failure {
  const request = store.requests.get(requestId);
  if (request === undefined) {
    return { ok: false, message: `申請 ${requestId} は見つかりません。` };
  }
  if (request.status !== "in_review") {
    return {
      ok: false,
      message: `申請 ${requestId} は ${request.status} のため決裁できません。決裁できるのは in_review の申請だけです。`,
    };
  }
  if (decision !== "approve" && (comment === undefined || comment.trim() === "")) {
    return {
      ok: false,
      message: `decision="${decision}" では comment（理由）が必須です。申請者に伝わる理由を 1 文以上で指定してください。`,
    };
  }

  const pending = request.approvals.filter((step) => step.state === "pending");
  const current = pending[0];
  if (current === undefined) {
    return { ok: false, message: `申請 ${requestId} に未処理の承認ステップがありません。` };
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
    previewToken: makePreviewToken({
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
): { ok: true; status: Status; stepLabel: string; finalizes: boolean } | Failure {
  const preview = previewDecision(store, requestId, decision, comment);
  if (!preview.ok) return preview;
  const request = store.requests.get(requestId) as WorkflowRequest;
  const current = request.approvals.find((step) => step.state === "pending") as ApprovalStep;
  const at = store.now();

  if (decision === "approve") {
    current.state = "approved";
    current.decidedAt = at;
  } else if (decision === "reject") {
    current.state = "rejected";
    current.decidedAt = at;
  } else {
    // 差し戻しは承認ルートを最初からやり直す
    request.approvals = approvalRoute(request.amountYen);
  }

  request.status = preview.nextStatus;
  request.updatedAt = at;
  request.history.push({
    at,
    actorId: current.approverId,
    action: decision,
    note: comment ?? "",
  });
  if (comment !== undefined && comment.trim() !== "") {
    request.comments.push({
      id: `c-${String(request.comments.length + 1).padStart(2, "0")}`,
      authorId: current.approverId,
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

// ---------------------------------------------------------------------------
// コメント
// ---------------------------------------------------------------------------

export function addComment(
  store: Store,
  requestId: string,
  body: string,
  links: string[],
): { ok: true; commentId: string; total: number } | Failure {
  const request = store.requests.get(requestId);
  if (request === undefined) {
    return { ok: false, message: `申請 ${requestId} は見つかりません。` };
  }
  const at = store.now();
  const commentId = `c-${String(request.comments.length + 1).padStart(2, "0")}`;
  const text = links.length === 0 ? body : `${body}\n参考: ${links.join(" ")}`;
  request.comments.push({ id: commentId, authorId: "u-900", body: text, postedAt: at });
  request.updatedAt = at;
  request.history.push({ at, actorId: "u-900", action: "commented", note: "" });
  return { ok: true, commentId, total: request.comments.length };
}
