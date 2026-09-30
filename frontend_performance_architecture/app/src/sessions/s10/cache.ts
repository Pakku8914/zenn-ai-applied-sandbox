import { toError } from './requestState';

/**
 * 失効の方針。
 * - staleMs 未満：新鮮。取得しない
 * - staleMs 以上 expireMs 未満：古いが見せてよい。見せながら裏で再検証する（stale-while-revalidate）
 * - expireMs 以上：失効。古すぎるので見せず、取り直す
 */
export type CachePolicy = { staleMs: number; expireMs: number };

export type Freshness = 'missing' | 'fresh' | 'stale' | 'expired';

/** 失効の判断だけを行う純粋な関数 */
export function judgeFreshness(fetchedAt: number | undefined, now: number, policy: CachePolicy): Freshness {
  if (fetchedAt === undefined) return 'missing';
  const age = now - fetchedAt;
  if (age < policy.staleMs) return 'fresh';
  if (age < policy.expireMs) return 'stale';
  return 'expired';
}

/** キャッシュから読んだ画面向けの状態。revalidating は「古いデータを出しつつ確認中」 */
export type QueryState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: Error }
  | { status: 'success'; data: T; revalidating: boolean };

type Entry<T> = { data?: T; fetchedAt?: number; error?: Error; inflight?: Promise<T>; state: QueryState<T> };

const LOADING = { status: 'loading' } as const;

export type QueryCacheOptions<T> = CachePolicy & {
  /** 取得：キーからデータを取る方法。キャッシュはこれがどこへ通信するかを知らない */
  fetcher: (key: string) => Promise<T>;
  now?: () => number;
};

export function createQueryCache<T>(options: QueryCacheOptions<T>) {
  const now = options.now ?? (() => Date.now());
  // キャッシュ：キー（取得の条件）ごとに結果を覚える
  const entries = new Map<string, Entry<T>>();
  const listeners = new Set<() => void>();

  function toState(entry: Entry<T>): QueryState<T> {
    if (entry.data !== undefined) {
      return { status: 'success', data: entry.data, revalidating: entry.inflight !== undefined };
    }
    if (entry.error !== undefined && entry.inflight === undefined) return { status: 'error', error: entry.error };
    return LOADING;
  }

  /** 状態のオブジェクトは変化したときだけ作り直す（useSyncExternalStore が同じ参照を期待するため） */
  function refresh(entry: Entry<T>): void {
    entry.state = toState(entry);
    for (const listener of listeners) listener();
  }

  /** 再検証：取り直す。同じキーの取得が進行中なら、新しく送らずにそれを共有する */
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
          target.fetchedAt = now();
          target.error = undefined;
          return data;
        },
        (error: unknown) => {
          // 裏での再検証に失敗しても、手元のデータは消さない（古くても見せ続ける）
          target.error = toError(error);
          throw target.error;
        },
      )
      .finally(() => {
        target.inflight = undefined;
        refresh(target);
      });
    target.inflight = promise;
    refresh(target);
    return promise;
  }

  /** 画面が「このキーのデータが要る」と伝える入口。鮮度に応じて取得するかを決める */
  function ensure(key: string): void {
    const freshness = judgeFreshness(entries.get(key)?.fetchedAt, now(), options);
    if (freshness === 'fresh') return;
    if (freshness === 'expired') entries.delete(key); // 失効：古すぎるデータは見せない
    revalidate(key).catch(() => undefined); // 失敗は state（error）で画面に伝える
  }

  return {
    ensure,
    revalidate,
    getState: (key: string): QueryState<T> => entries.get(key)?.state ?? LOADING,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export type QueryCache<T> = ReturnType<typeof createQueryCache<T>>;
