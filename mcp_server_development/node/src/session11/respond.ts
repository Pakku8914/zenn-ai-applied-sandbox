/**
 * 返す情報量を設計する部品
 *
 * 上限付き返却・本文の切り出し・部分成功の集約・返却量の計測をまとめています。
 * トークンの数え方はセッション10 の tokens.ts と同じ近似を使います
 * （尺度を変えると前章の数値と比べられなくなるため）。
 */
import type { DetailSection, WorkflowRequest } from "../session10/data.js";
import { estimateTokens } from "../session10/tokens.js";
import { failureText, type ErrorCode, type ToolFailure } from "./errors.js";

/**
 * サーバーが持つ上限。AI の指定に任せず、ここで決めます。
 * 値の根拠は「1 回のツール結果で会話履歴の 1% 程度に収める」という目安です。
 */
export const BUDGET = {
  /** 一覧テキストの上限（文字） */
  listChars: 1_200,
  /** 詳細の本文をそのまま返す上限（文字） */
  bodyChars: 400,
  /** コメント・添付・履歴を返す最大件数（直近から） */
  sectionItems: 5,
  /** 一括処理で受け付ける最大件数 */
  batchItems: 10,
} as const;

export type Fitted = { text: string; included: number; omitted: number };

/**
 * 行を上限まで詰め、切ったことと次の一手を最後に書き添える。
 *
 * 黙って切るのが最悪です。モデルは「これで全部だ」と解釈して結論を出します。
 */
export function fitLines(lines: readonly string[], maxChars: number, hint: string): Fitted {
  const kept: string[] = [];
  let used = 0;
  for (const line of lines) {
    if (used + line.length + 1 > maxChars) break;
    kept.push(line);
    used += line.length + 1;
  }
  const included = kept.length;
  const omitted = lines.length - included;
  if (omitted > 0) {
    kept.push(`…（返却上限 ${maxChars} 文字に達したため ${omitted} 件を省略しました。${hint}）`);
  }
  return { text: kept.join("\n"), included, omitted };
}

/** 長い本文は先頭だけを返し、全文の在処を書く */
export function fitBody(request: WorkflowRequest, maxChars: number = BUDGET.bodyChars): string {
  if (request.body.length <= maxChars) return request.body;
  return (
    `${request.body.slice(0, maxChars)}…\n` +
    `（本文は ${request.body.length} 文字あるため先頭 ${maxChars} 文字だけを返しました。` +
    `全文が必要なときはリソース request://${request.id} を読んでください）`
  );
}

/**
 * 本文の在処を示す参照。中身は運びません。
 * セッション5 の比喩で言えば「不在票」です。
 */
export function bodyLink(request: WorkflowRequest) {
  return {
    type: "resource_link" as const,
    uri: `request://${request.id}`,
    name: `${request.id}-body`,
    title: `申請 ${request.id} の本文`,
    mimeType: "text/plain",
    description: `本文の全文（${request.body.length} 文字）`,
  };
}

/** 直近 N 件だけを返す。古い記録より新しい記録のほうが判断に効くため後ろから取る */
function tailSection(label: string, items: readonly string[]): string[] {
  const shown = items.slice(-BUDGET.sectionItems);
  const suffix = items.length > shown.length ? `のうち直近 ${shown.length} 件` : "";
  return [`${label}（全 ${items.length} 件${suffix}）:`, ...shown];
}

/** 詳細の整形。include で選ばれたセクションだけを、件数上限付きで返す */
export function formatDetail(
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
    lines.push(
      ...tailSection(
        "コメント",
        request.comments.map((comment) => `- ${comment.authorId}: ${comment.body}`),
      ),
    );
  }
  if (include.includes("attachments")) {
    lines.push(
      ...tailSection(
        "添付",
        request.attachments.map((file) => `- ${file.fileName}（${file.sizeBytes} bytes）`),
      ),
    );
  }
  if (include.includes("history")) {
    lines.push(
      ...tailSection(
        "履歴",
        request.history.map((entry) => `- ${entry.at} ${entry.actorId} ${entry.action}`),
      ),
    );
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// 部分成功
// ---------------------------------------------------------------------------

export type ItemOutcome =
  | { id: string; ok: true; detail: string }
  | { id: string; ok: false; failure: ToolFailure };

export type BatchSummary = {
  text: string;
  succeeded: number;
  failed: number;
  retryableIds: string[];
  items: Array<{ id: string; ok: boolean; code?: ErrorCode; retryable?: boolean }>;
};

/**
 * 一括処理の結果をまとめる。
 *
 * 要点は 3 つです。
 *   ① 成否の要約を必ず 1 行目に置く（モデルは長い結果の途中を読み落とすことがある）
 *   ② 失敗したものは理由と次の一手を個別に書く
 *   ③ 「再試行してよい ID」を明示する（全体を再実行させないため）
 */
export function summarizeBatch(label: string, outcomes: readonly ItemOutcome[]): BatchSummary {
  const successes: string[] = [];
  const failures: string[] = [];
  const retryableIds: string[] = [];
  const items: BatchSummary["items"] = [];

  for (const outcome of outcomes) {
    if (outcome.ok) {
      successes.push(`成功 ${outcome.id}: ${outcome.detail}`);
      items.push({ id: outcome.id, ok: true });
      continue;
    }
    failures.push(
      `失敗 ${outcome.id}: [${outcome.failure.code}] ${outcome.failure.what} → ${outcome.failure.next}`,
    );
    items.push({
      id: outcome.id,
      ok: false,
      code: outcome.failure.code,
      retryable: outcome.failure.retryable,
    });
    if (outcome.failure.retryable) retryableIds.push(outcome.id);
  }

  const lines = [
    `${label}: ${outcomes.length} 件中 ${successes.length} 件成功・${failures.length} 件失敗`,
    ...successes,
    ...failures,
    retryableIds.length > 0
      ? `再試行してよい ID: ${retryableIds.join(", ")}（それ以外は同じ引数で呼び直しても結果は変わりません）`
      : "再試行してよい ID: なし（成功分は確定済みなので、全体を呼び直さないでください）",
  ];

  return {
    text: lines.join("\n"),
    succeeded: successes.length,
    failed: failures.length,
    retryableIds,
    items,
  };
}

/** 1 件だけの失敗を、一括処理の中の 1 行として書くときに使う */
export function outcomeLine(id: string, failure: ToolFailure): string {
  return `${id}: ${failureText(failure).split("\n")[0] ?? ""}`;
}

// ---------------------------------------------------------------------------
// 返却量の計測
// ---------------------------------------------------------------------------

export type ResponseSize = {
  contentChars: number;
  structuredChars: number;
  chars: number;
  tokens: number;
};

/**
 * ツール結果の大きさ（AI のコンテキストに載る量）を測る。
 * content と structuredContent を分けて測るのは、
 * 「同じ情報を二重に載せていないか」を見たいからです（6 節）。
 */
export function responseSize(result: {
  content?: unknown;
  structuredContent?: unknown;
  // callTool() の戻り値は旧形式とのユニオンなので、
  // インデックスシグネチャを付けてどちらの形でも受けられるようにする
  [key: string]: unknown;
}): ResponseSize {
  const contentJson = JSON.stringify(result.content ?? []);
  const structuredJson =
    result.structuredContent === undefined ? "" : JSON.stringify(result.structuredContent);
  return {
    contentChars: contentJson.length,
    structuredChars: structuredJson.length,
    chars: contentJson.length + structuredJson.length,
    tokens: estimateTokens(contentJson + structuredJson),
  };
}
