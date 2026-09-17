// 最終プロジェクト final01: 書店が守る資源の台帳。
// 注文台帳は中間プロジェクト①のものを import して使い（同じデータを 2 か所に持たない）、
// ここには在庫・担当店舗・売上の集計だけを置きます。
import type { Subject } from "../session02/api-authz-decide.js";
import { ORDERS, totalAmountOf } from "../mid01/mid01-orders.js";
import type { OrderDetail } from "../mid01/mid01-orders.js";

/** 応答に載せる注文の形。台帳の内部表現（ownerId を含む）をそのまま外に出しません */
export type OrderView = {
  orderId: string;
  title: string;
  amount: number;
  status: string;
  storeId: string;
};

export function orderView(order: OrderDetail): OrderView {
  return {
    orderId: order.orderId,
    title: order.title,
    amount: order.amount,
    status: order.status,
    storeId: order.storeId,
  };
}

/** 店舗の在庫。ISBN・店舗・在庫数はセッション 10 で使った 2 件と同じ値です */
export type StockItem = {
  readonly isbn: string;
  readonly storeId: string;
  readonly stock: number;
  readonly title: string;
};

export const INVENTORY: readonly StockItem[] = [
  { isbn: "978-4-00-000001-0", storeId: "shinjuku", stock: 12, title: "やさしい TypeScript 入門" },
  { isbn: "978-4-00-000002-7", storeId: "ueno", stock: 3, title: "くまのぼうけん（絵本）" },
];

/**
 * 店舗スタッフの担当店舗。トークンに載っていない属性は API 側の台帳から引きます（セッション 11）。
 * realm に属性マッパーを足していないので、ここが唯一の出どころです。
 */
const STAFF_STORES: Readonly<Record<string, string>> = { bob: "shinjuku" };

/** 利用者名から、認可の判断に渡す属性を作ります。担当が無い利用者は空のまま */
export function attributesOf(username: string): Subject["attributes"] {
  const storeId = STAFF_STORES[username];
  return storeId === undefined ? {} : { storeId };
}

/** 担当店舗の在庫だけ。絞り込む値が無いときは 1 件も返しません（安全側の既定） */
export function inventoryOf(storeId: string | undefined): StockItem[] {
  return storeId === undefined ? [] : INVENTORY.filter((item) => item.storeId === storeId);
}

export type StoreSales = { readonly storeId: string; readonly amount: number; readonly orderCount: number };

export type SalesReport = {
  readonly totalAmount: number;
  readonly orderCount: number;
  readonly canceledCount: number;
  readonly byStore: StoreSales[];
};

/** 夜間バッチが読む売上。取り消し済みは金額にも有効件数にも入れません */
export function salesReport(): SalesReport {
  const active = ORDERS.filter((order) => order.status !== "canceled");
  const storeIds = [...new Set(ORDERS.map((order) => order.storeId))].sort();
  return {
    totalAmount: totalAmountOf(ORDERS),
    orderCount: active.length,
    canceledCount: ORDERS.length - active.length,
    byStore: storeIds.map((storeId) => {
      const rows = active.filter((order) => order.storeId === storeId);
      return { storeId, amount: totalAmountOf(rows), orderCount: rows.length };
    }),
  };
}
