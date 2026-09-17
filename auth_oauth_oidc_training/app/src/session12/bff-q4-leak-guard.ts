// 問題 4 の解答: 応答のどこかにトークンが混ざっていないかを機械的に検査します。
// 「うっかり返してしまった」を人のレビューで防ぎ続けるのは無理なので、関所で落とします。
import { Hono } from "hono";
import type { MiddlewareHandler } from "hono";
import { setCookie } from "hono/cookie";

/**
 * JWT らしい文字列。
 * JOSE ヘッダは必ず `{"` で始まるので、base64url にすると eyJ から始まります。
 * ドットで 3 つに分かれていることまで見て、ただの長い文字列と区別します。
 */
const JWT_LIKE = /eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+/;

export type LeakSite = "header" | "set-cookie" | "body";

export type Leak = { readonly site: LeakSite; readonly detail: string };

/** 見つかった漏れの一覧。空なら漏れていません */
export async function findTokenLeaks(res: Response): Promise<readonly Leak[]> {
  const leaks: Leak[] = [];
  for (const [name, value] of res.headers.entries()) {
    // Set-Cookie は値が複数になりうるので、getSetCookie() で別に見ます
    if (name.toLowerCase() === "set-cookie") continue;
    if (JWT_LIKE.test(value)) leaks.push({ site: "header", detail: name.toLowerCase() });
  }
  for (const raw of res.headers.getSetCookie()) {
    if (JWT_LIKE.test(raw)) leaks.push({ site: "set-cookie", detail: raw.split("=")[0] ?? "" });
  }
  // clone() してから読む。元の応答の本文は手つかずのまま残ります
  if (JWT_LIKE.test(await res.clone().text())) leaks.push({ site: "body", detail: "応答本文" });
  return leaks;
}

/**
 * すべての応答を通す関所。漏れていたら応答ごと捨てて 500 にします。
 * 「漏らして 200 を返す」より「落ちる」ほうが被害が小さいという判断です。
 */
export function tokenLeakGuard(onLeak: (leaks: readonly Leak[]) => void = () => {}): MiddlewareHandler {
  return async (c, next) => {
    await next();
    const leaks = await findTokenLeaks(c.res);
    if (leaks.length === 0) return;
    onLeak(leaks);
    // 先に undefined を入れると、元の応答のヘッダを引き継がずに差し替えられます。
    // 差し替えには c.json() を使わず Response を直に作ります
    // （c.header() で積まれたヘッダが再び載り、同じものを漏らしてしまうため）。
    c.res = undefined;
    c.res = new Response(JSON.stringify({ error: "token_leak_blocked" }), {
      status: 500,
      headers: { "content-type": "application/json; charset=UTF-8" },
    });
  };
}

/**
 * 漏らしてしまう実装の例。デバッグ用の口を消し忘れたつもりです。
 * guard を渡すと関所を通すので、同じアプリで「通る／落ちる」を見比べられます。
 */
export function createLeakyApp(accessToken: string, guard?: MiddlewareHandler): Hono {
  const app = new Hono();
  if (guard !== undefined) {
    app.use("*", guard);
  }
  // 本文に入れてしまう例（「フロントで使いたい」と言われて足してしまう口）
  app.get("/bff/debug/token", (c) => c.json({ accessToken }));
  // ヘッダに入れてしまう例（ログ調査のために付けたまま忘れる）
  app.get("/bff/debug/header", (c) => {
    c.header("x-access-token", accessToken);
    return c.json({ ok: true });
  });
  // Cookie に入れてしまう例（HttpOnly を付けても「ブラウザに渡した」ことは変わらない）
  app.get("/bff/debug/cookie", (c) => {
    setCookie(c, "at", accessToken, { path: "/", httpOnly: true });
    return c.json({ ok: true });
  });
  // これは漏れていない応答（関所が誤検知しないことの確認に使う）
  app.get("/bff/orders", (c) => c.json({ orders: ["order-1001", "order-1002"] }));
  return app;
}
