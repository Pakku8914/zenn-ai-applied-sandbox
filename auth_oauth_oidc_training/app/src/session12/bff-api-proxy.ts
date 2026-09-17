// セッション 12: BFF（Backend for Frontend）。
// セッション 9 の RP に「ブラウザの代わりに api-service を呼ぶ口」を足しただけのものです。
// トークンは 1 文字もブラウザに渡りません（ブラウザが持つのはセッション ID だけ）。
import { Hono } from "hono";
import type { Context, MiddlewareHandler } from "hono";
import { deleteCookie, getCookie } from "hono/cookie";
import { createMiddleware } from "hono/factory";
import { callApi, defaultApiFetch } from "../mid01/mid01-api-client.js";
import type { ApiFetch } from "../mid01/mid01-api-client.js";
import { RP_BASE_URL } from "../session09/rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "../session09/rp-session-store.js";
import { createRpApp } from "../session09/rp-server.js";
import type { RpOptions } from "../session09/rp-server.js";

/** BFF がブラウザに返す状態。使うのはこの 4 つだけです */
export type BffStatus = 200 | 401 | 403 | 502;

export type BffOptions = {
  store?: RpSessionStore;
  config?: RpOptions["config"];
  cookieSecure?: boolean;
  /** api-service への問い合わせ口（中間プロジェクトで決めた型をそのまま使います） */
  apiFetch?: ApiFetch;
  /** 状態を変える呼び出しを受け付ける Origin。ここ以外から来たものは拒否します */
  allowedOrigin?: string;
};

export type BffApp = {
  /** ブラウザが話す相手。/login・/callback・/me に /bff/* を足したもの */
  readonly app: Hono;
  /** 検証で中身を覗くためにストアも返します */
  readonly store: RpSessionStore;
};

/**
 * 上流（api-service）の状態を、ブラウザに返す状態に翻訳します。
 * 500 番台をそのまま流すと API の内部事情がブラウザまで伝わるので、502 にまとめます。
 */
export function relayStatus(upstream: number): BffStatus {
  if (upstream === 200) return 200;
  // 401 は「BFF が持っているトークンが通らなかった」という意味です。
  // 本番ではここでリフレッシュを 1 回試します（練習問題 5 で実装します）。
  if (upstream === 401) return 401;
  if (upstream === 403) return 403;
  return 502;
}

/**
 * 同一オリジンからの呼び出しだけを通します。
 * BFF は Cookie で本人を確かめるので、他サイトに置かれたフォームやスクリプトから
 * 呼ばれると、利用者の意思なしに操作が実行されえます（CSRF）。
 * SameSite=Lax でも他サイトからのトップレベル遷移の GET には Cookie が付くため、
 * 状態を変える操作は必ず非 GET にして、この検査を通します。
 */
export function requireSameOrigin(allowedOrigin: string): MiddlewareHandler {
  return createMiddleware(async (c, next) => {
    const origin = c.req.header("origin");
    if (origin !== allowedOrigin) {
      // Origin が付いていない呼び出しも拒否します（「無いから通す」では検査した意味がありません）
      return c.json({ error: "cross_origin_request" }, 403);
    }
    await next();
    return;
  });
}

export async function createBffApp(options: BffOptions = {}): Promise<BffApp> {
  const store = options.store ?? new RpSessionStore();
  const apiFetch = options.apiFetch ?? defaultApiFetch;
  const allowedOrigin = options.allowedOrigin ?? RP_BASE_URL;
  // ログイン・コールバック・/me はセッション 9 の RP がそのまま使えます（作り直しません）
  const rp = await createRpApp({
    store,
    config: options.config,
    cookieSecure: options.cookieSecure,
  });

  /** セッションからアクセストークンを取り出します。トークンが出てくる場所はここだけです */
  const tokenOf = (c: Context): string | undefined => {
    const session = store.get(getCookie(c, SESSION_COOKIE));
    return session?.user === undefined ? undefined : session.tokens?.accessToken;
  };

  /** ブラウザの代わりに api-service を呼び、返ってきた JSON だけを渡します */
  const proxy = async (c: Context, path: string): Promise<Response> => {
    const accessToken = tokenOf(c);
    if (accessToken === undefined) {
      // ブラウザはトークンを持っていないので、ログイン状態の判定はここでしか行われません
      return c.json({ error: "unauthorized" }, 401);
    }
    const upstream = await callApi(apiFetch, path, accessToken);
    const status = relayStatus(upstream.status);
    c.header("cache-control", "no-store");
    if (status === 502) {
      // 上流の事情（内部エラーの本文）はブラウザに渡しません
      return c.json({ error: "upstream_error" }, 502);
    }
    const payload = (await upstream.json()) as Record<string, unknown>;
    return c.json(payload, status);
  };

  const app = new Hono();

  // ブラウザが呼ぶのはこちら。Authorization ヘッダではなく Cookie で本人を確かめます
  app.get("/bff/orders", (c) => proxy(c, "/api/orders"));
  app.get("/bff/inventory", (c) => proxy(c, "/api/inventory"));
  app.get("/bff/whoami", (c) => proxy(c, "/api/whoami"));

  // 状態を変える操作は非 GET にして、同一オリジンの検査を通します
  app.post("/bff/logout", requireSameOrigin(allowedOrigin), (c) => {
    const sessionId = getCookie(c, SESSION_COOKIE);
    store.destroy(sessionId); // サーバー側のトークンを消すのがログアウトの本体
    deleteCookie(c, SESSION_COOKIE, { path: "/" });
    c.header("cache-control", "no-store");
    return c.json({ loggedOut: true });
  });

  // 残りはセッション 9 の RP に任せます（/login・/callback・/me・/logout・/）
  app.route("/", rp);
  return { app, store };
}
