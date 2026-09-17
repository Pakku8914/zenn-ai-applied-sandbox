// セッション18の到達点。
//
// 「予測できる失敗」（数量が不正・商品が無い・在庫不足）は Result で返し、
// 外部（ファイル読み込み）が投げる例外は、この層の入口で Result に変換する。
// 上位の層は try / catch を書かずに、型に現れた失敗だけを処理すればよくなる。

import { loadCatalog } from '../session17/catalog';
import type { CatalogItem } from '../session17/catalog';
import { collectResults, err, ok, tryCatchAsync } from './result';
import type { Result } from './result';

/** 1明細あたりの数量の上限（セッション15で決めた値） */
export const MAX_CART_QUANTITY = 10;

/** この層で起こりうる「予測できる失敗」の全部。判別タグは本書共通の kind */
export type ShopError =
  | { kind: 'invalid_quantity'; input: string }
  | { kind: 'quantity_out_of_range'; value: number }
  | { kind: 'product_not_found'; productId: number }
  | { kind: 'out_of_stock'; productName: string; requested: number; available: number }
  | { kind: 'catalog_unavailable'; reason: string };

/** 到達しないはずの分岐で呼ぶ。case を1つ忘れると引数の型が never でなくなり落ちる */
function assertNever(value: never): never {
  throw new Error(`未対応の失敗があります: ${JSON.stringify(value)}`);
}

/** 失敗を利用者向けの1文にする */
export function describeShopError(error: ShopError): string {
  switch (error.kind) {
    case 'invalid_quantity':
      return `数量は整数で入力してください（受け取った値: ${error.input}）`;
    case 'quantity_out_of_range':
      return `数量は1以上${MAX_CART_QUANTITY}以下で指定してください（受け取った値: ${error.value}）`;
    case 'product_not_found':
      return `商品が見つかりません（productId: ${error.productId}）`;
    case 'out_of_stock':
      return `${error.productName}の在庫が足りません（希望 ${error.requested}点 / 在庫 ${error.available}点）`;
    case 'catalog_unavailable':
      return `商品カタログを読み込めませんでした（${error.reason}）`;
    default:
      return assertNever(error);
  }
}

/** 文字列の入力を数量に変換する。失敗の理由まで型に載せる */
export function parseQuantity(input: string): Result<number, ShopError> {
  const value = Number(input);

  if (input.trim() === '' || !Number.isInteger(value)) {
    const error: ShopError = { kind: 'invalid_quantity', input };
    return err(error);
  }
  if (value < 1 || value > MAX_CART_QUANTITY) {
    const error: ShopError = { kind: 'quantity_out_of_range', value };
    return err(error);
  }
  return ok(value);
}

/** カタログから商品を探す。「無い」は例外ではなく通常の戻り値 */
export function findCatalogItem(
  items: readonly CatalogItem[],
  productId: number
): Result<CatalogItem, ShopError> {
  const found = items.find((item) => item.id === productId);

  if (found === undefined) {
    const error: ShopError = { kind: 'product_not_found', productId };
    return err(error);
  }
  return ok(found);
}

export type Reservation = {
  productId: number;
  productName: string;
  quantity: number;
  lineTotal: number;
};

/** 在庫を引き当てる。足りなければ「どれだけ足りないか」を失敗として返す */
export function reserveStock(item: CatalogItem, quantity: number): Result<Reservation, ShopError> {
  if (item.stock < quantity) {
    const error: ShopError = {
      kind: 'out_of_stock',
      productName: item.name,
      requested: quantity,
      available: item.stock,
    };
    return err(error);
  }
  return ok({
    productId: item.id,
    productName: item.name,
    quantity,
    lineTotal: item.price * quantity,
  });
}

export function formatReservation(reservation: Reservation): string {
  return `${reservation.productName} × ${reservation.quantity}点 = ${reservation.lineTotal}円`;
}

/** 数量の検証 → 商品の特定 → 在庫の引当。どこかで失敗したらそこで打ち切る */
export function addToCart(
  items: readonly CatalogItem[],
  productId: number,
  quantityInput: string
): Result<Reservation, ShopError> {
  const quantity = parseQuantity(quantityInput);
  if (quantity.kind === 'error') {
    return quantity;
  }

  const item = findCatalogItem(items, productId);
  if (item.kind === 'error') {
    return item;
  }

  return reserveStock(item.value, quantity.value);
}

/**
 * 外部からの読み込み（例外を投げる）を境界で Result に変える。
 * loader を差し替えられるようにしてあるので、失敗の再現もテストできる。
 */
export async function loadCatalogSafely(
  loader: () => Promise<CatalogItem[]> = loadCatalog
): Promise<Result<CatalogItem[], ShopError>> {
  const result = await tryCatchAsync(loader);

  if (result.kind === 'error') {
    const error: ShopError = { kind: 'catalog_unavailable', reason: result.error.message };
    return err(error);
  }
  return ok(result.value);
}

export type ReservationRequest = { productId: number; quantityInput: string };

/**
 * アプリケーション層。カタログの読み込みと明細の作成をまとめ、
 * 失敗を「集めて」返す。ここが本章のエラー境界のひとつ。
 */
export async function buildReservations(
  requests: readonly ReservationRequest[],
  loader?: () => Promise<CatalogItem[]>
): Promise<Result<Reservation[], ShopError[]>> {
  const catalogResult = await loadCatalogSafely(loader);

  if (catalogResult.kind === 'error') {
    const errors: ShopError[] = [catalogResult.error];
    return err(errors);
  }

  const catalog = catalogResult.value;
  return collectResults(
    requests.map((request) => addToCart(catalog, request.productId, request.quantityInput))
  );
}
