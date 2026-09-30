import { ApiError, isAbortError, wait } from './fakeApi';

/** 待ちきれずに打ち切った失敗。中断（AbortError）とは区別する */
export class TimeoutError extends Error {
  constructor(ms: number) {
    super(`${ms}ms 以内に応答がありませんでした`);
    this.name = 'TimeoutError';
  }
}

/**
 * 1回の試行に制限時間を付ける。時間切れになったら signal で中断し、TimeoutError で失敗させる。
 * 呼び出し元の signal（画面を離れた等）が中断されたら、それにも従う。
 */
export async function withTimeout<T>(
  op: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  outer?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const onOuterAbort = () => controller.abort(outer?.reason);
  outer?.addEventListener('abort', onOuterAbort, { once: true });
  const timer = setTimeout(() => controller.abort(new TimeoutError(timeoutMs)), timeoutMs);
  try {
    return await op(controller.signal);
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener('abort', onOuterAbort);
  }
}

/** 待てば直る見込みがある失敗だけをリトライ対象にする */
export function isRetryable(error: unknown): boolean {
  if (isAbortError(error)) return false; // 利用者が中断した。やり直さない
  if (error instanceof TimeoutError) return true;
  if (error instanceof ApiError) return error.status === 408 || error.status === 429 || error.status >= 500;
  return false;
}

/** 指数バックオフ：1回目の待ちが base、以降は倍々。上限で頭打ちにする */
export function backoffDelay(retryIndex: number, baseDelayMs: number, maxDelayMs = 10_000): number {
  return Math.min(baseDelayMs * 2 ** retryIndex, maxDelayMs);
}

export type RetryOptions = {
  retries: number;
  baseDelayMs: number;
  timeoutMs: number;
  /** 同じ操作を2回送っても結果が変わらないか。false なら1回しか送らない */
  idempotent: boolean;
  signal?: AbortSignal;
  onRetry?: (retryIndex: number, delayMs: number, error: unknown) => void;
};

export async function withRetry<T>(op: (signal: AbortSignal) => Promise<T>, options: RetryOptions): Promise<T> {
  // 冪等でない操作（注文・送金・投稿など）は、失敗に見えても相手側で処理済みかもしれない
  const maxAttempts = options.idempotent ? options.retries + 1 : 1;
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await withTimeout(op, options.timeoutMs, options.signal);
    } catch (error) {
      if (attempt >= maxAttempts || !isRetryable(error) || options.signal?.aborted) throw error;
      const delayMs = backoffDelay(attempt - 1, options.baseDelayMs);
      options.onRetry?.(attempt - 1, delayMs, error);
      await wait(delayMs, options.signal);
    }
  }
}
