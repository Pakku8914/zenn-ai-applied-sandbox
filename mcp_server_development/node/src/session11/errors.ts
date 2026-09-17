/**
 * 構造化エラーの共通部品
 *
 * セッション10 の toolError（メッセージ 1 本だけ）を置き換えます。
 * ここで作るのは 2 つの表現です。
 *   ・AI が読んで自力で回復できる文面
 *   ・機械（リトライ機構・監視）が読める error オブジェクト
 *
 * このファイルはサーバープロセスの中で動くので stdout には一切書きません。
 * 失敗の詳細は console.error（stderr）にだけ出します。
 */

/**
 * ツール実行層で返す失敗の分類。
 * JSON-RPC の数値コード（-32602 など）とは別物で、こちらは自分で決める語彙です。
 * 数を増やしすぎないのが要点です（モデルが区別できる粒度で十分）。
 */
export const ERROR_CODES = [
  "not_found",
  "invalid_state",
  "invalid_argument",
  "forbidden",
  "upstream_unavailable",
  "internal",
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

/**
 * 失敗の記述。AI に見せる 3 要素をフィールドとして強制しています。
 *   what      : 何が起きたか（1 文）
 *   next      : どう直すか（次に呼ぶツール名・引数まで具体的に）
 *   retryable : 同じ引数で再試行して意味があるか
 *
 * 「3 要素を書き忘れられない型にする」のが、この型のいちばんの役目です。
 */
export type ToolFailure = {
  code: ErrorCode;
  what: string;
  next: string;
  retryable: boolean;
  /** retryable が true のときだけ意味を持つ。待つべき秒数 */
  retryAfterSeconds?: number;
};

/** AI に見せる文面。3 行に固定すると、モデルもユーザーも読み方を覚えられます */
export function failureText(failure: ToolFailure): string {
  const retry = failure.retryable
    ? `再試行: 可（${failure.retryAfterSeconds ?? 1} 秒ほど待ってから同じ引数で呼び直してください）`
    : "再試行: 不可（引数か対象の状態を変えないと結果は変わりません）";
  return [`[${failure.code}] ${failure.what}`, `次の一手: ${failure.next}`, retry].join("\n");
}

/** outputSchema を宣言していないツールの失敗（文章だけ） */
export function toolFailure(failure: ToolFailure) {
  return {
    content: [{ type: "text" as const, text: failureText(failure) }],
    isError: true,
  };
}

/** 機械可読なエラー。outputSchema に error として宣言しておきます */
export function errorPayload(failure: ToolFailure) {
  return {
    code: failure.code,
    retryable: failure.retryable,
    ...(failure.retryAfterSeconds === undefined
      ? {}
      : { retryAfterSeconds: failure.retryAfterSeconds }),
  };
}

/**
 * outputSchema を宣言したツールの失敗（文章＋機械可読な error）。
 *
 * base には「エラーでも形を保つための空の正しい値」を渡します。
 * 仕様上は isError: true のとき structuredContent を省略できますが、
 * 省略せずに形を保つと、クライアント側の型が 1 本で済みます。
 */
export function toolFailureWith(failure: ToolFailure, base: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: failureText(failure) }],
    structuredContent: { ...base, error: errorPayload(failure) },
    isError: true,
  };
}

/** 参照番号の連番。実運用ではリクエスト ID や trace ID を使います */
let internalErrorSeq = 0;

/**
 * 想定外の例外を「返してよい形」に変換する。
 *
 * 例外の中身（スタックトレース・内部ホスト名・SQL・接続文字列）は stderr にだけ出し、
 * AI とユーザーには参照番号だけを返します。ここが情報漏えいの分かれ目です。
 */
export function internalFailure(context: string, error: unknown): ToolFailure {
  internalErrorSeq += 1;
  const reference = `E-${String(internalErrorSeq).padStart(3, "0")}`;
  // stderr なので stdio トランスポートの通信路を汚しません
  console.error(`[internal] ${reference} ${context}:`, error);
  return {
    code: "internal",
    what: `処理中に内部エラーが発生しました（参照番号 ${reference}）。`,
    next: "同じ引数で呼び直しても同じ結果になります。参照番号をユーザーに伝えて、サーバー管理者に確認してもらってください。",
    retryable: false,
  };
}

/**
 * 引数の値をエラー文に引用するときのフィルタ。
 * 長すぎる値を切り、トークンらしい文字列は伏せます。
 * 「受け取った値をそのまま echo する」は漏えいと浪費の両方の入口です。
 */
export function quoteArg(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? null);
  if (/^[A-Za-z0-9_-]{24,}$/.test(text)) return "（トークンらしい値のため省略）";
  return text.length > 40 ? `${text.slice(0, 40)}…（以下省略）` : text;
}

/** 内部情報が混ざっていないかを機械的に確かめる（検証スクリプトとテストで使う） */
export const INTERNAL_MARKERS = ["ECONNREFUSED", "at Object.", "at async", "/app/", "10.0."] as const;

export function leaksInternalDetail(text: string): boolean {
  return INTERNAL_MARKERS.some((marker) => text.includes(marker));
}
