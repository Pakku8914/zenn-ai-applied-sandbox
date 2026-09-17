// 問題3: レスポンスのメタ情報（ステータスコード・Allow・Set-Cookie）を組み立てる。

import { describeShopError } from '../../session18/shop';
import type { ShopError } from '../../session18/shop';
import { buildSetCookieHeader } from '../http-tools';
import type { ApiErrorPayload } from '../error-status';

/** カートに入れられる明細の上限 */
export const MAX_CART_LINES = 3;

/** セッション18の失敗に「カートが満杯」を追加した版 */
export type ShopErrorV2 = ShopError | { kind: 'cart_full'; currentLines: number };

// kind を1つ足したので、この表にも1行足さないと型エラーになる（決め忘れを防げる）
const STATUS_BY_ERROR_KIND: Record<ShopErrorV2['kind'], number> = {
  invalid_quantity: 400,
  quantity_out_of_range: 400,
  product_not_found: 404,
  out_of_stock: 409,
  catalog_unavailable: 503,
  cart_full: 409,
};

export function toHttpStatusV2(error: ShopErrorV2): number {
  return STATUS_BY_ERROR_KIND[error.kind];
}

export function describeShopErrorV2(error: ShopErrorV2): string {
  if (error.kind === 'cart_full') {
    return `カートの明細が上限${MAX_CART_LINES}件に達しています（現在 ${error.currentLines}件）`;
  }
  // ここでの error は ShopError に絞り込まれている
  return describeShopError(error);
}

export function toErrorPayloadV2(error: ShopErrorV2): ApiErrorPayload {
  const status = toHttpStatusV2(error);
  const message =
    status >= 500 ? 'サーバー側の問題でリクエストを処理できませんでした' : describeShopErrorV2(error);

  return { error: { kind: error.kind, message } };
}

/** 405 で必ず添えるヘッダの値 */
export function buildAllowHeader(allowed: readonly string[]): string {
  return allowed.join(', ');
}

/**
 * ログイン後に渡すセッション Cookie。
 * HttpOnly / Secure / SameSite は最初から付ける（意味は「セッション25：認証と認可」で解説）。
 */
export function buildSessionCookie(sessionId: string): string {
  return buildSetCookieHeader('shop_session', sessionId, { maxAgeSeconds: 1800 });
}
