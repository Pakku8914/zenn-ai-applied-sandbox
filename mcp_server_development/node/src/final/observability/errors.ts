/**
 * 失敗の共通部品（セッション11 の errors.ts を最終プロジェクト用に整理したもの）
 *
 * AI に見せる 3 要素（何が / どう直す / 再試行可否）をフィールドとして強制します。
 * このファイルは MCP を知りません。
 */
export const ERROR_CODES = [
  "not_found",
  "invalid_state",
  "invalid_argument",
  "forbidden",
  "rate_limited",
  "upstream_unavailable",
  "internal",
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

export type ToolFailure = {
  code: ErrorCode;
  what: string;
  next: string;
  retryable: boolean;
  retryAfterSeconds?: number;
};

export type TextBlock = { type: "text"; text: string };
export type LinkBlock = {
  type: "resource_link";
  uri: string;
  name: string;
  title?: string;
  mimeType?: string;
  description?: string;
};
export type ContentBlock = TextBlock | LinkBlock;

export type ToolOutcome = {
  content: ContentBlock[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
};

/** 3 行に固定する。読み方を覚えられる形にすることが目的 */
export function failureText(failure: ToolFailure): string {
  const retry = failure.retryable
    ? `再試行: 可（${failure.retryAfterSeconds ?? 1} 秒ほど待ってから同じ引数で呼び直してください）`
    : "再試行: 不可（引数か対象の状態を変えないと結果は変わりません）";
  return [`[${failure.code}] ${failure.what}`, `次の一手: ${failure.next}`, retry].join("\n");
}

export function toolFailure(failure: ToolFailure): ToolOutcome {
  return { content: [{ type: "text", text: failureText(failure) }], isError: true };
}

export function errorPayload(failure: ToolFailure): Record<string, unknown> {
  return {
    code: failure.code,
    retryable: failure.retryable,
    ...(failure.retryAfterSeconds === undefined
      ? {}
      : { retryAfterSeconds: failure.retryAfterSeconds }),
  };
}

/** outputSchema を宣言したツール用。失敗しても構造化出力の形を崩さない */
export function toolFailureWith(
  failure: ToolFailure,
  base: Record<string, unknown>,
): ToolOutcome {
  return {
    content: [{ type: "text", text: failureText(failure) }],
    structuredContent: { ...base, error: errorPayload(failure) },
    isError: true,
  };
}

let internalErrorSeq = 0;

/** 例外の中身は stderr にだけ出し、AI には参照番号だけを返す */
export function internalFailure(context: string, error: unknown): ToolFailure {
  internalErrorSeq += 1;
  const reference = `E-${String(internalErrorSeq).padStart(3, "0")}`;
  console.error(`[internal] ${reference} ${context}:`, error);
  return {
    code: "internal",
    what: `処理中に内部エラーが発生しました（参照番号 ${reference}）。`,
    next: "同じ引数で呼び直しても結果は変わりません。参照番号をユーザーに伝え、サーバー管理者に確認してもらってください。",
    retryable: false,
  };
}

/** 引数をエラー文に引用するときのフィルタ。トークンらしい値は伏せ、長い値は切る */
export function quoteArg(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? null);
  if (/^[A-Za-z0-9_.-]{24,}$/.test(text)) return "（トークンらしい値のため省略）";
  return text.length > 40 ? `${text.slice(0, 40)}…（以下省略）` : text;
}

export const INTERNAL_MARKERS = ["at Object.", "at async", "/app/", "ECONNREFUSED", "10.0."] as const;

export function leaksInternalDetail(text: string): boolean {
  return INTERNAL_MARKERS.some((marker) => text.includes(marker));
}
