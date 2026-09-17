// 注文と利用者の台帳。トークンに載っていない情報はすべてここから引きます。
// 本番ではデータベースにあたる部分を、章では Map で代用しています。
import type { Order, Subject } from "../session02/api-authz-decide.js";

/** 持ち主がまだ分かっていない注文の ownerId。どの sub とも一致しません */
export const UNLINKED = "(未連携)";

type OrderRow = {
  readonly orderId: string;
  /** 認可サーバーの sub。初回ログインで判明した時点で埋めます */
  ownerSub: string;
  /** 題材の説明用の名前。判定には使いません */
  readonly ownerName: string;
  readonly storeId: string;
  readonly status: Order["status"];
};

/** セッション 2 で決めた題材の注文データ */
const SEED: ReadonlyArray<OrderRow> = [
  { orderId: "order-1001", ownerSub: UNLINKED, ownerName: "alice", storeId: "shinjuku", status: "paid" },
  { orderId: "order-1002", ownerSub: UNLINKED, ownerName: "alice", storeId: "shinjuku", status: "shipped" },
  { orderId: "order-1003", ownerSub: UNLINKED, ownerName: "alice", storeId: "shinjuku", status: "canceled" },
  { orderId: "order-2001", ownerSub: UNLINKED, ownerName: "bob", storeId: "shinjuku", status: "paid" },
  // alice の注文だが担当外店舗（ueno）のもの。bob から見れば担当外にあたる
  { orderId: "order-9001", ownerSub: UNLINKED, ownerName: "alice", storeId: "ueno", status: "paid" },
];

export class BookstoreDirectory {
  private readonly orders = new Map<string, OrderRow>();
  private readonly profiles = new Map<string, Subject["attributes"]>();

  constructor() {
    for (const row of SEED) this.orders.set(row.orderId, { ...row });
  }

  /**
   * 認可サーバーの sub と、アプリ側の利用者を紐づけます。
   * 本番でも同じことをします（初回ログインで sub を利用者レコードに保存する）。
   * 戻り値は、その sub の持ち物になった注文の件数です。
   */
  linkAccount(sub: string, username: string, attributes: Subject["attributes"] = {}): number {
    this.profiles.set(sub, attributes);
    let linked = 0;
    for (const row of this.orders.values()) {
      if (row.ownerName === username) {
        row.ownerSub = sub;
        linked += 1;
      }
    }
    return linked;
  }

  /** 判定に渡す資源。ownerId は sub です（利用者名ではありません） */
  order(orderId: string): Order | undefined {
    const row = this.orders.get(orderId);
    if (row === undefined) return undefined;
    return { orderId: row.orderId, ownerId: row.ownerSub, storeId: row.storeId, status: row.status };
  }

  /** トークンに載っていない属性（担当店舗・利用停止）を sub から引きます */
  attributesOf(sub: string): Subject["attributes"] {
    return this.profiles.get(sub) ?? {};
  }
}
