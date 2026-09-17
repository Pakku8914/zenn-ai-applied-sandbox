/**
 * レート制限（トークンバケット）
 *
 * 時刻を関数で受け取るのが要点です。内部で Date.now() を呼ぶと、テストが
 * 「1 秒待つ」ことになり、遅くて不安定（CI で稀に落ちる）になります。
 * 時計を注入すれば、実時間を 1 ミリ秒も待たずに「2.5 秒後」を試せます。
 */
export type RateLimitDecision =
  | { readonly allowed: true; readonly remaining: number }
  | { readonly allowed: false; readonly retryAfterMs: number };

export type RateLimiterOptions = {
  /** バケットの容量（＝瞬間的に許す最大回数） */
  readonly capacity: number;
  /** 1 秒あたりの回復量（＝定常状態で許す毎秒の回数） */
  readonly refillPerSecond: number;
  readonly now: () => number;
  /** 保持するキーの上限。無制限にするとメモリ枯渇の的になる */
  readonly maxKeys?: number;
};

export type RateLimiter = {
  tryConsume(key: string, cost?: number): RateLimitDecision;
  size(): number;
};

type Bucket = { tokens: number; updatedAt: number };

export const DEFAULT_MAX_KEYS = 1000;

export function createRateLimiter(options: RateLimiterOptions): RateLimiter {
  const { capacity, refillPerSecond, now } = options;
  const maxKeys = options.maxKeys ?? DEFAULT_MAX_KEYS;
  const buckets = new Map<string, Bucket>();

  /** 最も古いバケットを 1 つ捨てる。実運用では LRU か外部ストア（Redis 等）に置く */
  function evictOldest(): void {
    let oldestKey: string | undefined;
    let oldestAt = Number.POSITIVE_INFINITY;
    for (const [key, bucket] of buckets) {
      if (bucket.updatedAt < oldestAt) {
        oldestAt = bucket.updatedAt;
        oldestKey = key;
      }
    }
    if (oldestKey !== undefined) {
      buckets.delete(oldestKey);
    }
  }

  function tryConsume(key: string, cost = 1): RateLimitDecision {
    const at = now();
    const current = buckets.get(key);
    if (current === undefined && buckets.size >= maxKeys) {
      evictOldest();
    }
    const bucket = current ?? { tokens: capacity, updatedAt: at };
    const elapsedMs = Math.max(0, at - bucket.updatedAt);
    const tokens = Math.min(capacity, bucket.tokens + (elapsedMs / 1000) * refillPerSecond);

    if (tokens < cost) {
      // 残量は更新しておく（次回の判定で二重に回復させないため）
      buckets.set(key, { tokens, updatedAt: at });
      return { allowed: false, retryAfterMs: Math.ceil(((cost - tokens) / refillPerSecond) * 1000) };
    }
    buckets.set(key, { tokens: tokens - cost, updatedAt: at });
    return { allowed: true, remaining: Math.floor(tokens - cost) };
  }

  return { tryConsume, size: () => buckets.size };
}
