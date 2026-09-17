// セッション17「非同期処理」で使う汎用の非同期ユーティリティ。
// 本文・練習問題の解答で繰り返し使う部品をここにまとめている。

/** 指定ミリ秒だけ待つ Promise を返す */
export function delay(ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

/** 処理にかかったミリ秒を測る（値そのものは環境によって前後する） */
export async function measureMs(task: () => Promise<unknown>): Promise<number> {
  const startedAt = Date.now();
  await task();
  return Date.now() - startedAt;
}

/** 中断できる待機。signal が中断されたら reject する */
export function delayWithSignal(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    // すでに中断済みなら、待たずに失敗させる
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }

    const onAbort = (): void => {
      clearTimeout(timer);
      reject(signal.reason);
    };

    const timer = setTimeout(() => {
      // 正常に終わったら見張りを外す（外さないとゴミが残る）
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);

    signal.addEventListener('abort', onAbort, { once: true });
  });
}

/** 制限時間つきで処理を実行する。時間を超えたら signal を中断する */
export async function withTimeout<T>(
  task: (signal: AbortSignal) => Promise<T>,
  ms: number
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, ms);

  try {
    return await task(controller.signal);
  } finally {
    // 成功でも失敗でもタイマーを止める。止めないとプロセスが終わらない
    clearTimeout(timer);
  }
}

/**
 * 中断・タイムアウトによる失敗かどうかを判定する。
 * 中断エラーは Error ではなく DOMException で届くことがあるため、
 * instanceof ではなく name プロパティの有無で判定する。
 * name は環境やバージョンで変わりうるので、両方の名前を許容している。
 */
export function isAbortLike(error: unknown): boolean {
  if (typeof error !== 'object' || error === null || !('name' in error)) {
    return false;
  }

  const name = typeof error.name === 'string' ? error.name : '';
  return name === 'AbortError' || name === 'TimeoutError';
}

export type RetryOptions = {
  /** 追加で試す回数（合計の試行回数は retries + 1 回） */
  retries: number;
  /** 1回目の待ち時間（ミリ秒）。2回目以降は2倍ずつ増える */
  baseMs: number;
};

/** 失敗したら待ち時間を2倍にしながら再試行する（指数バックオフ） */
export async function retryWithBackoff<T>(
  task: () => Promise<T>,
  options: RetryOptions,
  onRetry?: (attempt: number, waitMs: number, error: unknown) => void
): Promise<T> {
  let lastError: unknown = new Error('リトライが1回も実行されませんでした');

  for (let attempt = 1; attempt <= options.retries + 1; attempt += 1) {
    try {
      return await task();
    } catch (error) {
      lastError = error;

      // 最後の試行で失敗したら、もう待たずに諦める
      if (attempt > options.retries) {
        break;
      }

      const waitMs = options.baseMs * 2 ** (attempt - 1);
      onRetry?.(attempt, waitMs, error);
      await delay(waitMs);
    }
  }

  throw lastError;
}

/** failCount 回だけ失敗し、その次に成功するスタブ（クロージャで回数を覚える） */
export function createFlakyTask(failCount: number): () => Promise<string> {
  let calls = 0;

  return async () => {
    calls += 1;

    if (calls <= failCount) {
      throw new Error(`一時的な失敗（${calls}回目）`);
    }

    return `成功（${calls}回目で成功）`;
  };
}

/** 2回目までは 200ms、3回目以降は 5ms で終わる中断対応のスタブ */
export function createSlowThenFastTask(): (signal: AbortSignal) => Promise<string> {
  let calls = 0;

  return async (signal) => {
    calls += 1;
    const ms = calls <= 2 ? 200 : 5;
    await delayWithSignal(ms, signal);
    return `成功（${calls}回目・${ms}ms）`;
  };
}
