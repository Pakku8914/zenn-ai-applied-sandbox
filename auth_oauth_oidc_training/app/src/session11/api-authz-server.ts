// 注文 API（api-service）。トークンの検証のうしろに、認可の判断を差し込みます。
import { Hono } from "hono";
import type { Context, MiddlewareHandler } from "hono";
import type { Action } from "../session02/api-authz-decide.js";
import { verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { extractFacts } from "./api-authz-claims.js";
import type { TokenFacts } from "./api-authz-claims.js";
import type { BookstoreDirectory } from "./api-authz-directory.js";
import { REQUIRED_SCOPES, authorize } from "./api-authz-policy.js";
import type { ScopeRequirements } from "./api-authz-policy.js";

/** このアプリのハンドラが c.get("facts") で受け取れるもの */
export type AuthzEnv = { Variables: { facts: TokenFacts } };

export type ApiResponse = {
  readonly status: 200 | 403 | 404;
  readonly body: Record<string, unknown>;
  readonly headers: Record<string, string>;
};

export type OrdersAppOptions = {
  /** 操作ごとのスコープ要件。省略すると厳しい側（設計どおり）になります */
  readonly requiredScopes?: ScopeRequirements;
  /** 拒否したときの記録先。本番では監査ログに送ります（セッション 16） */
  readonly onDeny?: (line: string) => void;
};

/**
 * Authorization ヘッダのトークンを検証し、判断材料を後続に渡すだけのミドルウェア。
 * セッション 10 で作った検証ミドルウェアがあるなら、そちらを使ってください。
 * ここでは章が単独で動くように、セッション 4 の verifyAccessToken を呼んでいます。
 */
export const requireToken: MiddlewareHandler<AuthzEnv> = async (c, next) => {
  const header = c.req.header("authorization") ?? "";
  const token = header.toLowerCase().startsWith("bearer ") ? header.slice(7).trim() : "";
  if (token === "") {
    // 誰か分からない → 401（認証が足りない）
    c.header("WWW-Authenticate", 'Bearer realm="api-service"');
    return c.json({ error: "invalid_request" }, 401);
  }
  try {
    const { payload } = await verifyAccessToken(token);
    c.set("facts", extractFacts(payload));
  } catch {
    c.header("WWW-Authenticate", 'Bearer error="invalid_token"');
    return c.json({ error: "invalid_token" }, 401);
  }
  await next();
  return;
};

export function createOrdersApp(
  directory: BookstoreDirectory,
  options: OrdersAppOptions = {},
): Hono<AuthzEnv> {
  const requiredScopes = options.requiredScopes ?? REQUIRED_SCOPES;
  const onDeny = options.onDeny ?? ((): void => {});

  /** 1 つの注文に対する 1 つの操作を、認可の結果に応じて処理します */
  const run = (facts: TokenFacts, action: Action, orderId: string): ApiResponse => {
    const order = directory.order(orderId);
    if (order === undefined) {
      return { status: 404, body: { error: "not_found" }, headers: {} };
    }

    const result = authorize(facts, action, order, {
      // 属性はトークンではなく API 側の台帳から渡す
      attributes: directory.attributesOf(facts.sub),
      requiredScopes,
    });

    if (!result.allow) {
      // 理由は記録に残し、応答には出さない（他人の注文の中身を教えてしまわないため）
      onDeny(`sub=${facts.sub} action=${action} order=${orderId} stage=${result.stage} reason=${result.reason}`);
      if (result.stage === "scope") {
        return {
          status: 403,
          body: { error: "insufficient_scope" },
          headers: { "WWW-Authenticate": `Bearer error="insufficient_scope", scope="${result.missing.join(" ")}"` },
        };
      }
      return { status: 403, body: { error: "forbidden" }, headers: {} };
    }

    return {
      status: 200,
      body: { orderId: order.orderId, action, status: order.status, actor: facts.username },
      headers: {},
    };
  };

  /** 判定の結果を Hono の応答に変換します（ハンドラの仕事はこれだけ） */
  const send = (c: Context<AuthzEnv>, res: ApiResponse) => {
    for (const [name, value] of Object.entries(res.headers)) c.header(name, value);
    return c.json(res.body, res.status);
  };

  const app = new Hono<AuthzEnv>();
  app.use("/orders/*", requireToken);
  app.get("/orders/:orderId", (c) => send(c, run(c.get("facts"), "read", c.req.param("orderId"))));
  app.post("/orders/:orderId/cancel", (c) => send(c, run(c.get("facts"), "cancel", c.req.param("orderId"))));
  app.post("/orders/:orderId/refund", (c) => send(c, run(c.get("facts"), "refund", c.req.param("orderId"))));
  return app;
}
