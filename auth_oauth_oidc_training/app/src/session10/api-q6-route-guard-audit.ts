// 問題 6 の解答: 登録済みのルートを列挙して、保護され忘れたエンドポイントが無いかを自動で確かめます。
import { Hono } from "hono";
import type { AccessTokenClaims, ApiEnv } from "./api-service-claims.js";
import { createApiApp } from "./api-service-app.js";
import { bearerAuth } from "./api-service-middleware.js";

/** トークンを要求しないエンドポイント。ここに挙げたものだけが 200 を返してよい */
export const PUBLIC_PATHS: readonly string[] = ["/health"];

export type GuardRow = {
  path: string;
  status: number;
  hasChallenge: boolean;
  /** 公開なら 200、保護対象なら 401 ＋ チャレンジ、が満たされているか */
  asDesigned: boolean;
};

/** 登録済みの GET ルートを列挙します（ミドルウェアの登録（ALL や * 付き）は除く） */
export function listGetPaths(app: Hono<ApiEnv>): string[] {
  const paths = app.routes
    .filter((route) => route.method === "GET" && !route.path.includes("*"))
    .map((route) => route.path);
  return [...new Set(paths)].sort();
}

/** すべての GET ルートをトークン無しで叩き、設計どおりの応答になっているかを調べます */
export async function auditRouteProtection(
  app: Hono<ApiEnv>,
  publicPaths: readonly string[] = PUBLIC_PATHS,
): Promise<GuardRow[]> {
  const rows: GuardRow[] = [];
  for (const path of listGetPaths(app)) {
    const res = await app.request(path);
    const hasChallenge = res.headers.get("www-authenticate") !== null;
    const isPublic = publicPaths.includes(path);
    rows.push({
      path,
      status: res.status,
      hasChallenge,
      asDesigned: isPublic ? res.status === 200 : res.status === 401 && hasChallenge,
    });
  }
  return rows;
}

/** 保護され忘れたパスの一覧（空配列なら漏れなし） */
export const unguardedPaths = (rows: readonly GuardRow[]): string[] =>
  rows.filter((row) => !row.asDesigned).map((row) => row.path);

/**
 * あとから足したエンドポイント。
 * app.use("/api/*") が先に登録されているので、ハンドラに何も書かなくても保護されます。
 */
export function createApiAppWithReviews(): Hono<ApiEnv> {
  const app = createApiApp();
  app.get("/api/reviews", (c) => c.json({ subject: c.get("claims").sub, reviews: [] }));
  return app;
}

/**
 * 実験用: ミドルウェアの登録をルート定義より後ろに置いたアプリ。
 * Hono は登録順にハンドラを積むので、先に登録したハンドラが応答を返してしまい、
 * bearerAuth() は実行されません（点検すると保護漏れとして検出されます）。
 */
export function createApiAppWithLateMiddleware(): Hono<ApiEnv> {
  const app = new Hono<ApiEnv>();
  app.get("/health", (c) => c.json({ status: "ok" }));
  app.get("/api/whoami", (c) => {
    // ミドルウェアが動いていないので、ここでは claims が入っていない
    const claims: AccessTokenClaims | undefined = c.get("claims");
    return c.json({ subject: claims === undefined ? null : claims.sub });
  });
  app.use("/api/*", bearerAuth()); // 遅すぎる登録
  return app;
}
