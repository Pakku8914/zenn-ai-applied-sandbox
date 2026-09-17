// 練習問題 5: ログイン後の戻り先（next）を安全に決める。オープンリダイレクトの抜け道を塞ぐ。
// 許すのは「アプリ内の相対パス」と「完全一致の許可リストに載った絶対 URL」だけです。

export type SafeRedirectOptions = {
  /** 外部への転送を許す完全一致の許可リスト（既定は空 ＝ 外部へは一切転送しない） */
  readonly allowlist?: readonly string[];
};

/**
 * next を安全な転送先だけに絞ります。安全でなければ null を返します。
 * - 先頭が 1 つのスラッシュで始まる相対パス（`/me` など）は許可
 * - `//evil` のプロトコル相対 URL、`/\evil` のバックスラッシュ細工は拒否
 * - `http://` などの絶対 URL は、許可リストに完全一致したときだけ許可
 */
export function safeRedirectTarget(next: string, options: SafeRedirectOptions = {}): string | null {
  const allowlist = options.allowlist ?? [];
  // 絶対 URL は完全一致の許可リストにあるときだけ通す
  if (allowlist.includes(next)) return next;

  // バックスラッシュはブラウザが「/」として扱う実装があるため、判定前にスラッシュへ寄せる
  const normalized = next.replace(/\\/g, "/");
  // 相対パスの条件: 先頭が 1 つのスラッシュで、2 文字目がスラッシュでない（// を弾く）
  if (/^\/[^/]/.test(normalized)) return next;
  // ルート単体は許可（トップに戻すだけなので外部へは飛ばない）
  if (normalized === "/") return "/";
  return null;
}

/** 複数の next を一括で判定します（表示・検証用） */
export function classifyTargets(
  targets: readonly string[],
  options: SafeRedirectOptions = {},
): { next: string; result: string | null }[] {
  return targets.map((next) => ({ next, result: safeRedirectTarget(next, options) }));
}
