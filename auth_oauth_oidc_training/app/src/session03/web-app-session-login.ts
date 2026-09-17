// 書店 web-app のパスワード認証とセッション管理。
// Cookie に入れるのはセッション ID だけ。利用者の情報はすべてサーバー側（SessionStore）に置きます。
import { Hono } from "hono";
import type { Context } from "hono";
import { deleteCookie, getCookie, setCookie } from "hono/cookie";
import { createUserStore, verifyPassword } from "./web-app-password-store.js";
import type { UserStore } from "./web-app-password-store.js";
import { SessionStore } from "./web-app-session-store.js";
import type { SessionRecord } from "./web-app-session-store.js";

export const SESSION_COOKIE = "sid";

export type WebAppOptions = {
  store?: SessionStore; // セッションの置き場所。渡さなければ新しく作る
  users?: UserStore; // 利用者の一覧。渡さなければ alice と bob を作る
  cookieSecure?: boolean; // Cookie に Secure を付けるか（学習環境は HTTP なので既定 false）
  // ログイン成功時に ID を再生成するか。既定 true。false は固定攻撃の再現用で、
  // 本番のコードに作ってはいけないスイッチ
  rotateSessionIdOnLogin?: boolean;
};

export async function createWebApp(options: WebAppOptions = {}) {
  const store = options.store ?? new SessionStore();
  const users = options.users ?? (await createUserStore());
  const cookieSecure = options.cookieSecure ?? false;
  const rotateSessionIdOnLogin = options.rotateSessionIdOnLogin ?? true;

  const putSessionCookie = (c: Context, id: string): void => {
    setCookie(c, SESSION_COOKIE, id, {
      path: "/", // 書店のすべてのパスに送る
      httpOnly: true, // JavaScript から読めなくする
      sameSite: "Lax", // 他サイトから出た POST には付けない
      secure: cookieSecure, // HTTPS 以外では送らない（本番では必ず true）
      // Max-Age を付けないので「ブラウザを閉じたら消える Cookie」になる
    });
  };

  // Cookie が無い／期限切れなら匿名セッションを 1 つ発行する（カートを入れる先が必要）
  const ensureSession = (c: Context): { id: string; record: SessionRecord } => {
    const id = getCookie(c, SESSION_COOKIE);
    const record = store.get(id);
    if (id !== undefined && record !== undefined) {
      return { id, record };
    }
    const created = store.create(null);
    putSessionCookie(c, created.id);
    return created;
  };

  const app = new Hono();

  app.get("/cart", (c) => {
    const { record } = ensureSession(c);
    return c.json({ username: record.username, cart: record.cart });
  });

  app.post("/cart", async (c) => {
    const body = await c.req.parseBody();
    const title = typeof body["title"] === "string" ? body["title"] : "";
    if (title === "") {
      return c.json({ error: "title_required" }, 400);
    }
    const { record } = ensureSession(c);
    record.cart.push(title);
    return c.json({ cart: record.cart });
  });

  app.post("/login", async (c) => {
    const body = await c.req.parseBody();
    const username = typeof body["username"] === "string" ? body["username"] : "";
    const password = typeof body["password"] === "string" ? body["password"] : "";

    const user = users.find(username);
    const authenticated = user !== undefined && (await verifyPassword(user.passwordHash, password));
    if (!authenticated || user === undefined) {
      // 「利用者がいない」と「パスワードが違う」を区別できる情報は返さない
      return c.json({ error: "invalid_credentials" }, 401);
    }

    const currentId = getCookie(c, SESSION_COOKIE);
    const session = rotateSessionIdOnLogin
      ? store.regenerate(currentId, user.username) // 対策あり: ID を作り直す
      : reuseSession(store, currentId, user.username); // 対策なし: ログイン前の ID を使い続ける
    putSessionCookie(c, session.id);
    c.header("cache-control", "no-store");
    return c.json({ username: user.username, roles: user.roles, cart: session.record.cart });
  });

  app.get("/me", (c) => {
    const record = store.get(getCookie(c, SESSION_COOKIE));
    if (record === undefined || record.username === null) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const user = users.find(record.username);
    c.header("cache-control", "no-store");
    return c.json({ username: record.username, roles: user?.roles ?? [], cart: record.cart });
  });

  app.post("/logout", (c) => {
    const id = getCookie(c, SESSION_COOKIE);
    store.destroy(id); // 本体はサーバー側のレコードを消すこと
    deleteCookie(c, SESSION_COOKIE, { path: "/" }); // ブラウザ側の掃除はおまけ
    return c.json({ ok: true });
  });

  return app;
}

// 対策なしのログイン（セッション固定攻撃が成立する書き方）。比較のためだけに置いています。
function reuseSession(store: SessionStore, currentId: string | undefined, username: string) {
  const record = store.get(currentId);
  if (currentId !== undefined && record !== undefined) {
    record.username = username;
    return { id: currentId, record };
  }
  return store.create(username);
}
