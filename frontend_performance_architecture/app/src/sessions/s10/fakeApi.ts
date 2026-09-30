import { products, type Product } from '../../data/products';

/** 失敗した応答。status は HTTP のステータスコードを模したもの */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** 呼び出し1回ぶんの記録。検証スクリプトが回数・並列度・中断を数えるために使う */
export type ApiCall = {
  op: string;
  key: string;
  startedAt: number;
  endedAt?: number;
  outcome?: 'ok' | 'error' | 'aborted';
};

export type FakeApiOptions = {
  /** 検索以外の読み取りの応答時間（ms） */
  latencyMs?: number;
  /** 書き込み（お気に入りの保存）の応答時間（ms） */
  mutationLatencyMs?: number;
  /** 検索の応答時間。既定は searchLatency（キーワードが短いほど遅い） */
  searchLatency?: (keyword: string) => number;
  /** 失敗させる条件。乱数は使わず、呼び出し回数と ID で決める */
  failOn?: {
    /** 最初の N 回の呼び出しを 503 で失敗させる（リトライの題材） */
    firstCalls?: number;
    /** この ID のお気に入り保存を 500 で失敗させる（ロールバックの題材） */
    favoriteIds?: readonly number[];
  };
  /** 時刻の取り方。テストでは偽のタイマーに合わせて Date.now を渡す */
  now?: () => number;
};

/**
 * キーワードが短いほど一致する件数が多く、応答が遅い、という状況を決定的に作る。
 * '' → 900ms、「商」→ 700ms、「商品」→ 500ms、「商品1」→ 300ms
 */
export function searchLatency(keyword: string): number {
  return Math.max(100, 900 - keyword.length * 200);
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

/** 中断の合図（signal）を受け取れる待ち時間。中断されたら signal.reason で失敗する */
export function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/** 意図的に遅延・失敗する擬似 API。バックエンドを立てずに、取得の設計を試すために使う */
export function createFakeApi(options: FakeApiOptions = {}) {
  const now = options.now ?? (() => performance.now());
  const latencyMs = options.latencyMs ?? 300;
  const mutationLatencyMs = options.mutationLatencyMs ?? 800;
  const latencyOf = options.searchLatency ?? searchLatency;
  const failFirst = options.failOn?.firstCalls ?? 0;
  const failFavorites = options.failOn?.favoriteIds ?? [];
  const calls: ApiCall[] = [];

  async function run<T>(op: string, key: string, ms: number, signal: AbortSignal | undefined, body: () => T): Promise<T> {
    const call: ApiCall = { op, key, startedAt: now() };
    calls.push(call);
    const callNumber = calls.length;
    try {
      await wait(ms, signal);
      if (callNumber <= failFirst) {
        throw new ApiError(503, `一時的に応答できません（${callNumber} 回目の呼び出し）`);
      }
      const result = body();
      call.outcome = 'ok';
      return result;
    } catch (error) {
      call.outcome = isAbortError(error) ? 'aborted' : 'error';
      throw error;
    } finally {
      call.endedAt = now();
    }
  }

  return {
    calls,
    searchProducts(keyword: string, signal?: AbortSignal): Promise<Product[]> {
      return run('search', keyword, latencyOf(keyword), signal, () => products.filter((p) => p.name.includes(keyword)));
    },
    getProducts(signal?: AbortSignal): Promise<Product[]> {
      return run('products', '', latencyMs, signal, () => products);
    },
    getCategories(signal?: AbortSignal): Promise<string[]> {
      return run('categories', '', latencyMs, signal, () => ['文具', '書籍', '雑貨', '食品']);
    },
    /** 価格の高い順に上位 5 件 */
    getRanking(signal?: AbortSignal): Promise<Product[]> {
      return run('ranking', '', latencyMs, signal, () => [...products].sort((a, b) => b.price - a.price).slice(0, 5));
    },
    setFavorite(id: number, on: boolean, signal?: AbortSignal): Promise<{ id: number; on: boolean }> {
      return run('favorite', String(id), mutationLatencyMs, signal, () => {
        if (failFavorites.includes(id)) throw new ApiError(500, `商品${id} のお気に入りを保存できませんでした`);
        return { id, on };
      });
    },
  };
}

export type FakeApi = ReturnType<typeof createFakeApi>;
