// セッション 14: オープンリダイレクトを利用した認可コード横取りの再現と対策。
// 対象は同梱サンドボックスの中の自分のクライアント（web-app）だけです。
// ここでは「うっかりリダイレクト」を持つ RP と、それを塞いだ RP を並べて、
// 届いた認可コードが外部へ漏れるかどうかを自分の目で確かめます。
import { Hono } from "hono";

/**
 * オープンリダイレクトを持つ RP（Bad）。
 * next に渡された URL を検証せずにブラウザを転送します。
 * コールバックに残ったクエリ（code を含む）も一緒に運ばれるため、認可コードが外部へ漏れます。
 */
export function createVulnerableRp(): Hono {
  const app = new Hono();
  app.get("/legacy-redirect", (c) => {
    const url = new URL(c.req.url);
    const next = url.searchParams.get("next") ?? "/";
    // Bad: next をそのまま信じて転送する。手元のクエリ（code・state・iss）も付けて運んでしまう
    const target = new URL(next);
    for (const [key, value] of url.searchParams) {
      if (key !== "next") target.searchParams.set(key, value);
    }
    return c.redirect(target.toString(), 302);
  });
  return app;
}

/**
 * オープンリダイレクトを塞いだ RP（Good）。
 * 転送先を「アプリ内の相対パス」だけに限り、外部の絶対 URL・プロトコル相対 URL を拒否します。
 */
export function createSafeRp(): Hono {
  const app = new Hono();
  app.get("/legacy-redirect", (c) => {
    const next = new URL(c.req.url).searchParams.get("next") ?? "/";
    // Good: 先頭が 1 つのスラッシュで始まる相対パスだけを許す（// や http:// は拒否）
    if (next !== "/" && !/^\/[^/\\]/.test(next)) {
      return c.json({ error: "invalid_redirect_target" }, 400);
    }
    return c.redirect(next, 302);
  });
  return app;
}
