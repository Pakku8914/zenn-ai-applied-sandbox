/**
 * 横断復習4 の共通部品
 *
 * セッション10（定義サイズの計測）とセッション11（構造化エラー）、
 * セッション12（スコープ）で作った部品を、この章だけで完結する形にまとめ直しました。
 * 関数名は各章の本文と同じにしてあるので、記憶がそのまま使えます。
 *
 * このファイルはサーバープロセスの中で動くので stdout には一切書きません。
 */

// ── セッション10: ツール定義のサイズを測る ───────────────────────────────
/** ASCII は 4 文字 ≒ 1 トークン、非 ASCII は 1 文字 ≒ 1 トークンとして概算する */
export function estimateTokens(text: string): number {
  let ascii = 0;
  let wide = 0;
  for (const ch of text) {
    if ((ch.codePointAt(0) ?? 0) < 128) ascii++;
    else wide++;
  }
  return Math.ceil(ascii / 4) + wide;
}

export type ToolSize = { name: string; chars: number; tokens: number };
export type Measured = { rows: ToolSize[]; totalChars: number; totalTokens: number };

export function measureTools(tools: Array<{ name: string }>): Measured {
  const rows = tools
    .map((tool) => {
      const json = JSON.stringify(tool);
      return { name: tool.name, chars: json.length, tokens: estimateTokens(json) };
    })
    .sort((a, b) => (a.name < b.name ? -1 : 1));
  return {
    rows,
    totalChars: rows.reduce((sum, row) => sum + row.chars, 0),
    totalTokens: rows.reduce((sum, row) => sum + row.tokens, 0),
  };
}

// ── セッション11: 構造化エラー ───────────────────────────────────────────
export const ERROR_CODES = [
  "not_found",
  "invalid_state",
  "invalid_argument",
  "forbidden",
  "upstream_unavailable",
  "internal",
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

/** 3 要素（何が / どう直す / 再試行可否）を書き忘れられない型 */
export type ToolFailure = {
  code: ErrorCode;
  what: string;
  next: string;
  retryable: boolean;
  retryAfterSeconds?: number;
};

export function failureText(failure: ToolFailure): string {
  const retry = failure.retryable
    ? `再試行: 可（${failure.retryAfterSeconds ?? 1} 秒ほど待ってから同じ引数で呼び直してください）`
    : "再試行: 不可（引数か対象の状態を変えないと結果は変わりません）";
  return [`[${failure.code}] ${failure.what}`, `次の一手: ${failure.next}`, retry].join("\n");
}

export function toolFailure(failure: ToolFailure) {
  return { content: [{ type: "text" as const, text: failureText(failure) }], isError: true };
}

export function errorPayload(failure: ToolFailure) {
  return {
    code: failure.code,
    retryable: failure.retryable,
    ...(failure.retryAfterSeconds === undefined
      ? {}
      : { retryAfterSeconds: failure.retryAfterSeconds }),
  };
}

/** outputSchema を宣言したツールの失敗（形を保ったまま error を足す） */
export function toolFailureWith(failure: ToolFailure, base: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: failureText(failure) }],
    structuredContent: { ...base, error: errorPayload(failure) },
    isError: true,
  };
}

let internalErrorSeq = 0;

/** 想定外の例外を「返してよい形」に変換する。詳細は stderr にだけ出す */
export function internalFailure(context: string, error: unknown): ToolFailure {
  internalErrorSeq += 1;
  const reference = `E-${String(internalErrorSeq).padStart(3, "0")}`;
  console.error(`[internal] ${reference} ${context}:`, error);
  return {
    code: "internal",
    what: `処理中に内部エラーが発生しました（参照番号 ${reference}）。`,
    next: "同じ引数で呼び直しても同じ結果になります。参照番号をユーザーに伝えて、サーバー管理者に確認してもらってください。",
    retryable: false,
  };
}

export const INTERNAL_MARKERS = [
  "ECONNREFUSED",
  "ETIMEDOUT",
  "at Object.",
  "at async",
  "/app/",
  "10.0.",
  "Bearer ",
] as const;

/** 内部情報が混ざっていないかを機械的に確かめる（検証とハーネスで使う） */
export function leaksInternalDetail(text: string): boolean {
  return INTERNAL_MARKERS.some((marker) => text.includes(marker));
}

// ── セッション12: スコープ ───────────────────────────────────────────────
export const SCOPE_READ = "requests:read";
export const SCOPE_WRITE = "requests:write";
export const SCOPE_APPROVE = "requests:approve";
export const SUPPORTED_SCOPES: readonly string[] = [SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE];

/** ツール名 → 必要スコープ。表で持つと監査でき、漏れを機械的に検出できる */
export const TOOL_SCOPES: Readonly<Record<string, string>> = {
  search_requests: SCOPE_READ,
  get_request: SCOPE_READ,
  summarize_requests: SCOPE_READ,
  create_request: SCOPE_WRITE,
  decide_request: SCOPE_APPROVE,
};

/**
 * ツール単位のスコープ検査。足りなければツール実行層の失敗（isError）を返す。
 *
 * セッション12 の本文は AsyncLocalStorage で認証文脈を運びましたが、
 * ここでは granted を引数で受け取ります。理由は 1 つで、HTTP を立てずに
 * インメモリ接続でテストできるようにするためです（セッション13 の伏線）。
 */
export function scopeFailure(tool: string, granted: readonly string[]): ToolFailure | undefined {
  const required = TOOL_SCOPES[tool];
  if (required === undefined || granted.includes(required)) return undefined;
  const list = granted.length === 0 ? "なし" : granted.join(", ");
  return {
    code: "forbidden",
    what: `ツール ${tool} の実行には権限 ${required} が必要です。`,
    next: `いま付与されている権限は ${list} です。${required} の付与を管理者に依頼してください。読み取りだけなら search_requests が使えます。`,
    retryable: false,
  };
}
