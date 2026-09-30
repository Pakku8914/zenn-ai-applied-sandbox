import { judgeFreshness, type QueryCacheOptions, type QueryState } from '../cache';
import { toError } from '../requestState';

type Entry<T> = {
  data?: T;
  fetchedAt?: number;
  error?: Error;
  inflight?: Promise<T>;
  /** 取得の途中で無効化された。届いた応答は変更前のデータかもしれないので新鮮扱いしない */
  invalidatedWhileInflight?: boolean;
  state: QueryState<T>;
};

const LOADING = { status: 'loading' } as const;

/** 問題7：本文の createQueryCache に invalidate を足したもの（差分は invalidate と invalidatedWhileInflight だけ） */
export function createInvalidatingCache<T>(options: QueryCacheOptions<T>) {
  const now = options.now ?? (() => Date.now());
  const entries = new Map<string, Entry<T>>();
  const listeners = new Set<() => void>();

  function toState(entry: Entry<T>): QueryState<T> {
    if (entry.data !== undefined) {
      return { status: 'success', data: entry.data, revalidating: entry.inflight !== undefined };
    }
    if (entry.error !== undefined && entry.inflight === undefined) return { status: 'error', error: entry.error };
    return LOADING;
  }

  function refresh(entry: Entry<T>): void {
    entry.state = toState(entry);
    for (const listener of listeners) listener();
  }

  function revalidate(key: string): Promise<T> {
    let entry = entries.get(key);
    if (entry === undefined) {
      entry = { state: LOADING };
      entries.set(key, entry);
    }
    if (entry.inflight !== undefined) return entry.inflight;

    const target = entry;
    const promise = options
      .fetcher(key)
      .then(
        (data) => {
          target.data = data;
          // 途中で無効化されていたら、次の ensure で必ず取り直す
          target.fetchedAt = target.invalidatedWhileInflight ? undefined : now();
          target.error = undefined;
          return data;
        },
        (error: unknown) => {
          target.error = toError(error);
          throw target.error;
        },
      )
      .finally(() => {
        target.inflight = undefined;
        target.invalidatedWhileInflight = false;
        refresh(target);
      });
    target.inflight = promise;
    refresh(target);
    return promise;
  }

  function ensure(key: string): void {
    const freshness = judgeFreshness(entries.get(key)?.fetchedAt, now(), options);
    if (freshness === 'fresh') return;
    if (freshness === 'expired') entries.delete(key);
    revalidate(key).catch(() => undefined);
  }

  /**
   * 条件に合うキーを「取り直しが必要」にする。データは消さない（次の取得が終わるまで古い値を見せる）。
   * 返り値は無効化したキーの数。
   */
  function invalidate(match: (key: string) => boolean): number {
    let count = 0;
    for (const [key, entry] of entries) {
      if (!match(key)) continue;
      entry.fetchedAt = undefined;
      if (entry.inflight !== undefined) entry.invalidatedWhileInflight = true;
      count += 1;
    }
    return count;
  }

  return {
    ensure,
    revalidate,
    invalidate,
    getState(key: string): QueryState<T> {
      return entries.get(key)?.state ?? LOADING;
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
