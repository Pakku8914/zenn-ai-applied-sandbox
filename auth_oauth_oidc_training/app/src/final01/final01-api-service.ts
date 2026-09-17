// 最終プロジェクト final01: リソースサーバー（api-service）。
// 検証はセッション 10 の bearerAuth()、判断は final01-authz.ts、記録はセッション 16 に任せます。
// このファイルの仕事は「どの経路に何を通すか」を宣言することだけです。
import { Hono } from "hono";
import type { Context } from "hono";
import { createMiddleware } from "hono/factory";
import { findOrder, totalAmountOf } from "../mid01/mid01-orders.js";
import type { Subject } from "../session02/api-authz-decide.js";
import { forbidden } from "../session10/api-service-challenge.js";
import type { AccessTokenClaims, ApiEnv } from "../session10/api-service-claims.js";
import { bearerAuth } from "../session10/api-service-middleware.js";
import type { BearerAuthOptions } from "../session10/api-service-middleware.js";
import { extractFacts } from "../session11/api-authz-claims.js";
import type { TokenFacts } from "../session11/api-authz-claims.js";
import { auditFromClaims, auditRejection } from "../session16/api-service-audit-log.js";
import type { Outcome } from "../session16/api-service-audit-log.js";
import { createAuditSink } from "./final01-audit.js";
import type { AuditSink } from "./final01-audit.js";
import {
  BookstoreAccounts,
  asResource,
  decideInventory,
  decideOrder,
  decideReport,
  outcomeOf,
  visibleOrders,
} from "./final01-authz.js";
import { attributesOf, inventoryOf, orderView, salesReport } from "./final01-catalog.js";

export type FinalApiOptions = BearerAuthOptions & {
  /** sub と書店の利用者の対応表。渡さなければ新しく作ります */
  accounts?: BookstoreAccounts;
  /** 監査ログの出口。渡さなければ何も表示しません */
  audit?: AuditSink;
};

/** ハンドラが見てよい判断材料。ここから先で claims を直接読みません */
type Caller = {
  readonly facts: TokenFacts;
  /** sub に結び付いた書店の利用者名 */
  readonly ownerId: string;
  readonly attributes: Subject["attributes"];
};

export function createFinalApiApp(options: FinalApiOptions = {}): Hono<ApiEnv> {
  const accounts = options.accounts ?? new BookstoreAccounts();
  const audit = options.audit ?? createAuditSink();
  const app = new Hono<ApiEnv>();

  const routeOf = (c: Context<ApiEnv>): string => `${c.req.method} ${new URL(c.req.url).pathname}`;
  const ipOf = (c: Context<ApiEnv>): string => c.req.header("x-forwarded-for") ?? "";

  // 認証に関わる応答はキャッシュさせない。経路を足しても漏れないよう出口で一括して付ける
  app.use("*", async (c, next) => {
    await next();
    c.res.headers.set("cache-control", "no-store");
  });

  /** 判断の結果を記録します。記録してよい項目は auditFromClaims() が決めます */
  const record = (
    c: Context<ApiEnv>,
    claims: AccessTokenClaims,
    outcome: Outcome,
    extra: Record<string, unknown> = {},
  ): void => {
    audit.write({ ...auditFromClaims(claims, outcome, { ip: ipOf(c) }), route: routeOf(c), ...extra });
  };

  // 検証に失敗した呼び出しも記録する。bearerAuth() の外側に置き、返ってきた 401 を拾う
  const auditToken = createMiddleware<ApiEnv>(async (c, next) => {
    await next();
    if (c.res.status === 401) {
      // auditRejection() はトークンから何も読まない（信用できないクレームを記録しない）
      audit.write({
        ...auditRejection(c.res.headers.get("www-authenticate") ?? "", { ip: ipOf(c) }),
        route: routeOf(c),
      });
    }
  });

  const auth = bearerAuth(options);
  // 保護する経路をここに並べて宣言する。書き忘れた経路は「トークン無しで通る経路」になる
  app.use("/orders", auditToken, auth);
  app.use("/orders/*", auditToken, auth);
  app.use("/inventory", auditToken, auth);
  app.use("/reports/*", auditToken, auth);

  // トークンが要らない唯一の経路
  app.get("/health", (c) => c.json({ status: "ok", service: "api-service" }));

  /** 初めて見た sub を利用者に結び付け、トークンに無い属性を台帳から足します */
  const callerOf = (c: Context<ApiEnv>): Caller => {
    const facts = extractFacts(c.get("claims"));
    const ownerId = accounts.link(facts.sub, facts.username);
    return { facts, ownerId, attributes: attributesOf(ownerId) };
  };

  // 1. 自分に見える注文の一覧。返す前に絞る
  app.get("/orders", (c) => {
    const { facts, ownerId, attributes } = callerOf(c);
    const orders = visibleOrders(facts, accounts, attributes);
    record(c, c.get("claims"), {
      event: "authz.granted",
      decision: "allow",
      reason: `${orders.length} 件を返しました`,
    });
    return c.json({
      owner: ownerId,
      roles: [...facts.realmRoles],
      count: orders.length,
      totalAmount: totalAmountOf(orders),
      orders: orders.map(orderView),
    });
  });

  // 2. 注文 1 件。無ければ 404、許されなければ 403
  app.get("/orders/:orderId", (c) => {
    const { facts, attributes } = callerOf(c);
    const order = findOrder(c.req.param("orderId"));
    if (order === undefined) {
      return c.json({ error: "not_found" }, 404);
    }
    const result = decideOrder(facts, "read", asResource(order, accounts), attributes);
    record(c, c.get("claims"), outcomeOf(result), { resource: order.orderId, stage: result.stage });
    if (!result.allow) {
      // 「持ち主でない」と「担当店舗でない」を区別して伝えない（資源の中身を推測させない）
      return forbidden(c, "この注文を参照する権限がありません");
    }
    return c.json({ order: orderView(order) });
  });

  // 3. 担当店舗の在庫。staff ロールが無ければ 403
  app.get("/inventory", (c) => {
    const { facts, attributes } = callerOf(c);
    const result = decideInventory(facts, attributes);
    record(c, c.get("claims"), outcomeOf(result), { stage: result.stage });
    if (!result.allow) {
      // 必要な権限の名前は伝えてよい（資源の存在を教えることにはならない）
      return forbidden(c, result.reason);
    }
    return c.json({ storeId: attributes.storeId ?? "", items: inventoryOf(attributes.storeId) });
  });

  // 4. 売上の集計。利用者不在のトークンだけに許す。対応表には触らない
  app.get("/reports/daily", (c) => {
    const claims = c.get("claims");
    const result = decideReport(claims.azp ?? "");
    record(c, claims, outcomeOf(result), { stage: result.stage });
    if (!result.allow) {
      return forbidden(c, "この集計を参照する権限がありません");
    }
    return c.json({ report: salesReport() });
  });

  return app;
}
