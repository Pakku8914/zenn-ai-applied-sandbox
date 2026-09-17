// 問題 5 の解答: ログイン試行の回数制限と、利用者名の存在を漏らさない応答。
// 実行: docker compose exec app npx tsx src/session03/web-app-q5-login-throttle.ts
import { pathToFileURL } from "node:url";
import { Hono } from "hono";
import { getCookie, setCookie } from "hono/cookie";
import { createUserStore, hashPassword, verifyPassword } from "./web-app-password-store.js";
import { SessionStore } from "./web-app-session-store.js";
import { SESSION_COOKIE } from "./web-app-session-login.js";
import { call } from "./web-app-cookie-tools.js";

export type ThrottleOptions = {
  /** 時計。テストでは好きな時刻を差し込める */
  now?: () => number;
  /** 何回失敗したらロックするか（既定 5 回） */
  maxAttempts?: number;
  /** ロックしている時間（既定 60 秒） */
  lockMs?: number;
};

type FailureState = { count: number; lockedUntil: number };

export async function createThrottledLoginApp(options: ThrottleOptions = {}) {
  const now = options.now ?? (() => Date.now());
  const maxAttempts = options.maxAttempts ?? 5;
  const lockMs = options.lockMs ?? 60_000;

  const users = await createUserStore();
  const store = new SessionStore();
  // 存在しない利用者名のときに使う「捨てハッシュ」。検証にかかる時間をそろえるために使う
  const dummyHash = await hashPassword("dummy-password-for-timing");
  const failures = new Map<string, FailureState>();

  const app = new Hono();

  app.post("/login", async (c) => {
    const body = await c.req.parseBody();
    const username = typeof body["username"] === "string" ? body["username"] : "";
    const password = typeof body["password"] === "string" ? body["password"] : "";
    const key = username.toLowerCase();

    const state = failures.get(key);
    if (state !== undefined && state.lockedUntil > now()) {
      const retryAfter = Math.ceil((state.lockedUntil - now()) / 1000);
      c.header("retry-after", String(retryAfter));
      // ロック中は、パスワードが正しいかどうかも判定しない（判定させるとそこが探索の手がかりになる）
      return c.json({ error: "too_many_attempts" }, 429);
    }

    // ロック期間が明けたら失敗回数を捨てる（明けた直後の 1 回で即再ロックさせない）
    const lockExpired = state !== undefined && state.lockedUntil !== 0 && state.lockedUntil <= now();
    const previousCount = lockExpired ? 0 : (state?.count ?? 0);

    const user = users.find(username);
    // 存在しない利用者名でも必ず 1 回ハッシュ検証を行う（応答時間の差から存在を推測させない）
    const matched = await verifyPassword(user?.passwordHash ?? dummyHash, password);
    if (!matched || user === undefined) {
      const count = previousCount + 1;
      failures.set(key, {
        count,
        lockedUntil: count >= maxAttempts ? now() + lockMs : 0,
      });
      // 失敗の理由は 1 種類しか返さない
      return c.json({ error: "invalid_credentials" }, 401);
    }

    failures.delete(key); // 成功したら失敗回数を捨てる
    const session = store.regenerate(getCookie(c, SESSION_COOKIE), user.username);
    setCookie(c, SESSION_COOKIE, session.id, {
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
      secure: false, // 学習環境は HTTP のため false。本番では必ず true
    });
    return c.json({ username: user.username }, 200);
  });

  app.get("/me", (c) => {
    const record = store.get(getCookie(c, SESSION_COOKIE));
    if (record === undefined || record.username === null) {
      return c.json({ error: "unauthorized" }, 401);
    }
    return c.json({ username: record.username });
  });

  return app;
}

async function main(): Promise<void> {
  let clock = 0;
  const app = await createThrottledLoginApp({ now: () => clock, maxAttempts: 5, lockMs: 60_000 });
  const wrong = { username: "alice", password: "wrong-pass" };
  const right = { username: "alice", password: "alice-pass" };

  console.log("=== ログイン試行の回数制限 ===");
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    const res = await call(app, "/login", { method: "POST", form: wrong });
    console.log(`失敗 ${attempt} 回目 : ${res.status}`);
  }
  const locked = await call(app, "/login", { method: "POST", form: right });
  console.log(`ロック中に正しいパスワード : ${locked.status}`);

  clock += 60_001; // 時計を進めてロックを明かす（実時間は待たない）
  const unlocked = await call(app, "/login", { method: "POST", form: right });
  console.log(`60 秒後に正しいパスワード : ${unlocked.status}`);

  const unknown = await call(app, "/login", {
    method: "POST",
    form: { username: "nobody", password: "wrong-pass" },
  });
  console.log(`存在しない利用者名 : ${unknown.status} ${unknown.body}`);
}

const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  await main();
}
