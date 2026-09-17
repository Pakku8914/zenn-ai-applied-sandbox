// セッション20「WebとHTTPの基礎・Node.jsサーバー」
//
// この章の山場。セッション18で作った「予測できる失敗」（ShopError）を、
// HTTP のステータスコードに写す1枚の表。
// アプリの中の言葉（kind）と、Web の共通語（ステータスコード）の翻訳表にあたる。

import { describeShopError } from '../session18/shop';
import type { ShopError } from '../session18/shop';

/**
 * 失敗の種類 → ステータスコードの対応表。
 * Record で書くと、ShopError に kind を足したときにこの表が型エラーになり、
 * 「新しい失敗をどのステータスコードで返すか」を決め忘れられなくなる。
 */
const STATUS_BY_ERROR_KIND: Record<ShopError['kind'], number> = {
  invalid_quantity: 400, // 入力の形が違う（直せるのはクライアント）
  quantity_out_of_range: 400, // 範囲外の数量
  product_not_found: 404, // そのIDの商品は無い
  out_of_stock: 409, // 形は正しいが、いまの在庫と矛盾している
  catalog_unavailable: 503, // こちら側の都合で一時的に応えられない
};

export function toHttpStatus(error: ShopError): number {
  return STATUS_BY_ERROR_KIND[error.kind];
}

/** クライアントに返す失敗の形。アプリ内の kind をそのまま名前として使う */
export type ApiErrorPayload = { error: { kind: string; message: string } };

/**
 * 失敗をレスポンスの本文にする。
 * 5xx（原因が自分たちの側にある失敗）では内部のメッセージを外に出さない。
 * ファイルパスや例外の文面は、攻撃者にとってのヒントになる。
 */
export function toErrorPayload(error: ShopError): ApiErrorPayload {
  const status = toHttpStatus(error);
  const message =
    status >= 500
      ? 'サーバー側の問題でリクエストを処理できませんでした'
      : describeShopError(error);

  return { error: { kind: error.kind, message } };
}
