import type { Product } from '../../data/products';
import { ApiError, createFakeApi, type FakeApi } from '../s10/fakeApi';

/** ライブリージョンの更新を待つ時間。入力のたびに読み上げが割り込まないよう、打ち終わってから 1 回だけ伝える */
export const LIVE_DELAY_MS = 300;
export const DEFAULT_LATENCY_MS = 300;
/** ?fail=favorite のとき、お気に入りの保存に失敗させる商品 */
export const FAIL_FAVORITE_ID = 1;

export type CatalogOptions = {
  /** 一覧の読み込みにかける時間（ms）。?latency=10000 でスケルトンを長く見せる */
  latencyMs: number;
  /** ?fail=load … 最初の読み込みを 503 で失敗させる */
  failLoad: boolean;
  /** ?fail=favorite … 商品1 のお気に入り保存を失敗させる */
  failFavorite: boolean;
  /** ?live=eager … デバウンスせず、入力のたびにライブリージョンを書き換える（比較用） */
  liveDelayMs: number;
};

export function parseOptions(search: string): CatalogOptions {
  const params = new URLSearchParams(search);
  const latency = Number(params.get('latency') ?? DEFAULT_LATENCY_MS);
  const fail = params.getAll('fail');
  return {
    latencyMs: Number.isFinite(latency) && latency >= 0 ? latency : DEFAULT_LATENCY_MS,
    failLoad: fail.includes('load'),
    failFavorite: fail.includes('favorite'),
    liveDelayMs: params.get('live') === 'eager' ? 0 : LIVE_DELAY_MS,
  };
}

export function createCatalogApi(options: CatalogOptions): FakeApi {
  return createFakeApi({
    latencyMs: options.latencyMs,
    failOn: { favoriteIds: options.failFavorite ? [FAIL_FAVORITE_ID] : [] },
  });
}

/**
 * 一覧を読み込む。failFirstAttempt なら 1 回目（attempt 0）だけ失敗させる。
 * 呼び出し回数ではなく attempt で決めるので、開発時の StrictMode で effect が 2 回走っても結果は同じ。
 */
export async function loadCatalog(
  api: FakeApi,
  { attempt, failFirstAttempt, signal }: { attempt: number; failFirstAttempt: boolean; signal?: AbortSignal },
): Promise<readonly Product[]> {
  const items = await api.getProducts(signal);
  if (failFirstAttempt && attempt === 0) throw new ApiError(503, '一時的に応答できません');
  return items;
}
