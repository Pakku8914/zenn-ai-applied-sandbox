// 書店の注文 API（api-service）。検証はミドルウェアに任せ、ハンドラは中身だけを書きます。
// 使い方: createApiApp() で Hono アプリを作り、app.request() か serve() で動かします。
import { Hono } from "hono";
import { audiencesOf, rolesOf } from "./api-service-claims.js";
import type { ApiEnv } from "./api-service-claims.js";
import { bearerAuth, requireRealmRole } from "./api-service-middleware.js";
import type { BearerAuthOptions } from "./api-service-middleware.js";

/** セッション 2 から使っている注文データ。誰にどれを見せるかの判断はセッション 11 の担当です */
const ORDERS = [
  { id: "order-1001", storeId: "shinjuku", total: 2800 },
  { id: "order-1002", storeId: "shinjuku", total: 3200 },
  { id: "order-9001", storeId: "ueno", total: 2400 },
];

const INVENTORY = [
  { isbn: "978-4-00-000001-0", storeId: "shinjuku", stock: 12 },
  { isbn: "978-4-00-000002-7", storeId: "ueno", stock: 3 },
];

export function createApiApp(options: BearerAuthOptions = {}): Hono<ApiEnv> {
  const app = new Hono<ApiEnv>();

  // トークンが要らないエンドポイント。保護の対象外であることが 1 か所で分かるようにする
  app.get("/health", (c) => c.json({ status: "ok", service: "api-service" }));

  // ここから下の /api/* はすべて検証済みになる（ハンドラ側に検証を書かない）
  app.use("/api/*", bearerAuth(options));

  app.get("/api/whoami", (c) => {
    const claims = c.get("claims");
    return c.json({
      subject: claims.sub,
      username: claims.preferred_username ?? null,
      client: claims.azp ?? null,
      audiences: audiencesOf(claims),
      roles: rolesOf(claims),
      expiresIn: Math.max(0, claims.exp - Math.floor(Date.now() / 1000)),
    });
  });

  app.get("/api/orders", (c) => {
    const claims = c.get("claims");
    return c.json({ subject: claims.sub, orders: ORDERS.map((order) => order.id) });
  });

  // 403 の例。ロールの設計そのものはセッション 11 で扱うので、ここでは 1 つだけ要求します
  app.get("/api/inventory", requireRealmRole("staff"), (c) => c.json({ inventory: INVENTORY }));

  return app;
}
