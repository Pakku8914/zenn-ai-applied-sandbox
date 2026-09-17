// 中間プロジェクト mid01: リソースサーバー（api-service）。
// トークンを検証し、認可を判断し、注文を返すだけのサーバーです。トークンは 1 本も発行しません。
// 認証（誰か）は mid01-api-auth.ts、認可（何を許すか）はセッション 2 の decide() が担当します。
import { Hono } from "hono";
import type { Context } from "hono";
import { decide } from "../session02/api-authz-decide.js";
import type { Subject } from "../session02/api-authz-decide.js";
import { AccountLinks } from "./mid01-accounts.js";
import { authenticate } from "./mid01-api-auth.js";
import type { AuthFailure } from "./mid01-api-auth.js";
import { findOrder, ordersOf, totalAmountOf } from "./mid01-orders.js";
import type { OrderDetail } from "./mid01-orders.js";

export type ApiOptions = {
  /** sub と利用者の対応表。渡さなければ新しく作ります */
  links?: AccountLinks;
  /** 失敗の理由を書き出す先。既定では何も出しません（検証を静かに走らせるため） */
  log?: (message: string) => void;
};

/** 401 のときに必ず返す「この API はどうやって認証するのか」の案内（RFC 6750 §3） */
const REALM_CHALLENGE = 'Bearer realm="bookstore"';

/** 応答に載せる注文の形。台帳の内部表現（OrderDetail）をそのまま外に出しません */
function toJson(order: OrderDetail): {
  orderId: string;
  title: string;
  amount: number;
  status: string;
  storeId: string;
} {
  return {
    orderId: order.orderId,
    title: order.title,
    amount: order.amount,
    status: order.status,
    storeId: order.storeId,
  };
}

export function createApiApp(options: ApiOptions = {}): Hono {
  const links = options.links ?? new AccountLinks();
  const log = options.log ?? ((): void => undefined);
  const app = new Hono();
  // 認証に関わる応答はキャッシュさせない。個々のハンドラで付け忘れないよう、
  // 出口で一括して付ける（1 か所にまとめれば、経路を足しても漏れない）
  app.use("*", async (c, next) => {
    await next();
    c.res.headers.set("cache-control", "no-store");
  });

  /** 401 の作法。本文よりも WWW-Authenticate ヘッダが本体です */
  const unauthorized = (c: Context, failure: AuthFailure): Response => {
    const challenge =
      failure.error === undefined ? REALM_CHALLENGE : `${REALM_CHALLENGE}, error="${failure.error}"`;
    c.header("www-authenticate", challenge);
    // 理由はログにだけ残します。攻撃者に「どこまで合っていたか」を教えないため
    log(`[api-service] 401 ${failure.logReason}`);
    return c.json({ error: "unauthorized" }, 401);
  };

  /** トークンから「書店の利用者」を決めます。sub を鍵にするのがこの関数の要点です */
  const ownerIdOf = (sub: string, username: string): string => links.link(sub, username);

  // 1. 自分の注文一覧。返すのは「呼び出し元が持ち主である注文」だけです
  app.get("/orders", async (c) => {
    const auth = await authenticate(c.req.header("authorization"));
    if (!auth.ok) {
      return unauthorized(c, auth);
    }
    const ownerId = ownerIdOf(auth.caller.sub, auth.caller.username);
    const orders = ordersOf(ownerId); // 絞り込みは「返す前」に行う（全件返して画面で隠さない）
    return c.json({
      owner: ownerId,
      count: orders.length,
      totalAmount: totalAmountOf(orders),
      orders: orders.map(toJson),
    });
  });

  // 2. 注文 1 件。無ければ 404、持ち主でなければ 403
  app.get("/orders/:orderId", async (c) => {
    const auth = await authenticate(c.req.header("authorization"));
    if (!auth.ok) {
      return unauthorized(c, auth);
    }
    const order = findOrder(c.req.param("orderId"));
    if (order === undefined) {
      return c.json({ error: "not_found" }, 404);
    }
    // 認可の判断はセッション 2 の decide() に任せます。
    // roles を空にしているのは、ロールを使った判断をこのプロジェクトの範囲外に置いているためです。
    const subject: Subject = {
      userId: ownerIdOf(auth.caller.sub, auth.caller.username),
      roles: [],
      attributes: {},
    };
    const decision = decide(subject, "read", order);
    if (!decision.allow) {
      log(`[api-service] 403 ${subject.userId} → ${order.orderId}（${decision.reason}）`);
      return c.json({ error: "forbidden", reason: decision.reason }, 403);
    }
    return c.json({ order: toJson(order) });
  });

  return app;
}
