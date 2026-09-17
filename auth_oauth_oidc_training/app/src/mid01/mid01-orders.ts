// 中間プロジェクト mid01: 書店の注文台帳（api-service が守る資源）。
// 注文 ID・店舗 ID・状態はセッション 2 で決めた値をそのまま使います（別の値を作らない）。
import type { Order } from "../session02/api-authz-decide.js";

/**
 * 表示用の情報を足した注文。
 * 認可の判断に使う 4 項目（orderId / ownerId / storeId / status）はセッション 2 の Order をそのまま継ぎ、
 * 画面に出す title と amount だけを足します。判断の材料と表示の材料を混ぜないための形です。
 */
export type OrderDetail = Order & {
  readonly title: string;
  /** 税込の合計金額（円） */
  readonly amount: number;
};

/** 書店の注文台帳。データベースの代わりに定数で持ちます（このプロジェクトの主題は認可なので） */
export const ORDERS: readonly OrderDetail[] = [
  { orderId: "order-1001", ownerId: "alice", storeId: "shinjuku", status: "paid", title: "やさしい TypeScript 入門", amount: 3200 },
  { orderId: "order-1002", ownerId: "alice", storeId: "shinjuku", status: "shipped", title: "HTTP の教科書", amount: 2800 },
  { orderId: "order-1003", ownerId: "alice", storeId: "shinjuku", status: "canceled", title: "図解 データベース入門", amount: 4100 },
  { orderId: "order-2001", ownerId: "bob", storeId: "shinjuku", status: "paid", title: "在庫管理の基本", amount: 3600 },
  { orderId: "order-9001", ownerId: "alice", storeId: "ueno", status: "canceled", title: "くまのぼうけん（絵本）", amount: 1500 },
];

/** 注文 ID で 1 件引きます。無ければ undefined（404 にするかどうかは呼ぶ側が決めます） */
export function findOrder(orderId: string): OrderDetail | undefined {
  return ORDERS.find((order) => order.orderId === orderId);
}

/** ある利用者の注文だけを、台帳の順に返します */
export function ordersOf(ownerId: string): OrderDetail[] {
  return ORDERS.filter((order) => order.ownerId === ownerId);
}

/** 合計金額。取り消した注文は合計に入れません（取り消した買い物を支払額に数えないため） */
export function totalAmountOf(orders: readonly OrderDetail[]): number {
  return orders
    .filter((order) => order.status !== "canceled")
    .reduce((sum, order) => sum + order.amount, 0);
}
