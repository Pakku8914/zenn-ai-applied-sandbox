/**
 * 読み込み関数を「成功したら結果を使い回し、失敗したら次の呼び出しでやり直す」形に包む。
 * - 先読み（ホバー）と本番（クリック）で import() が二重に走らない
 * - 一度失敗しても、失敗した Promise を覚えたままにしない（押し直せば再取得する）
 */
export function onceWithRetry<T>(load: () => Promise<T>): () => Promise<T> {
  let pending: Promise<T> | null = null;
  return () => {
    if (pending === null) {
      pending = load().catch((error: unknown) => {
        pending = null;
        throw error;
      });
    }
    return pending;
  };
}
