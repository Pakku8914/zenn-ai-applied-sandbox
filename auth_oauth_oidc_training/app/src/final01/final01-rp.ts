// 最終プロジェクト final01: 書店のフロント（web-app）。RP（リライング・パーティ）です。
// /login・/callback・/me・/logout・/ はセッション 9 の RP をそのまま使い（app.route で丸ごと取り込む）、
// その外側に「入口の関門」「監査ログ」「トークンの関門」「api-service を呼ぶ 3 経路」を足します。
// トークンは 1 文字もブラウザに渡りません。ブラウザが持つのはセッション ID だけです。
import { Hono } from "hono";
import type { Context } from "hono";
import { getCookie } from "hono/cookie";
import type { Configuration } from "openid-client";
import { callApi, defaultApiFetch } from "../mid01/mid01-api-client.js";
import type { ApiErrorPayload, ApiFetch, ApiOrder } from "../mid01/mid01-api-client.js";
import { parseSetCookie } from "../session03/web-app-cookie-tools.js";
import { CLIENT_ID } from "../session06/bookstore-client.js";
import { getOpenIdConfig } from "../session09/rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "../session09/rp-session-store.js";
import type { RpSession } from "../session09/rp-session-store.js";
import { createRpApp } from "../session09/rp-server.js";
import { relayStatus } from "../session12/bff-api-proxy.js";
import { revokeToken } from "../session16/api-service-revocation-policy.js";
import { createAuditSink, rpAuditRecord } from "./final01-audit.js";
import type { AuditSink, RpAuditEvent } from "./final01-audit.js";
import { checkAuthorizationUrl } from "./final01-login-policy.js";
import { RefreshRotation, guardAccessToken } from "./final01-token-guard.js";

export type FinalWebOptions = {
  store?: RpSessionStore;
  config?: Configuration;
  cookieSecure?: boolean;
  /** api-service への問い合わせ口。検証では Hono の app.request を差し込みます */
  apiFetch?: ApiFetch;
  audit?: AuditSink;
  rotation?: RefreshRotation;
};

export type FinalWebApp = {
  readonly app: Hono;
  /** 検証と運用の点検で中身を覗くために返します */
  readonly store: RpSessionStore;
  readonly rotation: RefreshRotation;
  readonly audit: AuditSink;
};

/** api-service が返した失敗の本文（403 の message を受け取るため） */
type ApiFailure = ApiErrorPayload & { message?: string };

type OrdersPayload = {
  owner?: string;
  roles?: string[];
  count?: number;
  totalAmount?: number;
  orders?: ApiOrder[];
};

type InventoryPayload = {
  storeId?: string;
  items?: Array<{ isbn: string; title: string; stock: number; storeId: string }>;
};

/** api-service を呼べたか、呼ぶ前に落としたか */
type RelayResult =
  | { readonly ok: true; readonly upstream: Response; readonly session: RpSession }
  | { readonly ok: false; readonly res: Response };

export async function createFinalWebApp(options: FinalWebOptions = {}): Promise<FinalWebApp> {
  const store = options.store ?? new RpSessionStore();
  const rotation = options.rotation ?? new RefreshRotation();
  const audit = options.audit ?? createAuditSink();
  const apiFetch = options.apiFetch ?? defaultApiFetch;
  const config = options.config ?? (await getOpenIdConfig());
  // ログインの 5 経路はセッション 9 の RP がそのまま使える（作り直さない）
  const rp = await createRpApp({ store, config, cookieSecure: options.cookieSecure });

  const note = (event: RpAuditEvent, sub: string, reason: string, extra: Record<string, unknown> = {}): void => {
    audit.write({ ...rpAuditRecord({ event, sub, clientId: CLIENT_ID, reason }), ...extra });
  };

  const app = new Hono();
  app.use("*", async (c, next) => {
    await next();
    c.res.headers.set("cache-control", "no-store");
  });

  // 1. ログインの開始。セッション 9 の /login を内側で呼び、転送先を検査してから返す
  app.get("/login", async (c) => {
    const res = await rp.request("/login");
    const location = res.headers.get("location");
    const violation = location === null ? "missing_code_challenge" : checkAuthorizationUrl(new URL(location));
    if (violation !== undefined) {
      note("login.policy_violation", "", violation);
      // 方針を満たさないログインは始めさせない（利用者をどこにも転送しない）
      return c.json({ error: "login_policy_violation", violation }, 500);
    }
    return res; // Set-Cookie も含めてそのまま返す
  });

  // 2. コールバック。検証はセッション 9 に任せ、成否だけを記録する
  app.get("/callback", async (c) => {
    const res = await rp.request(`/callback${new URL(c.req.url).search}`, {
      headers: { cookie: c.req.header("cookie") ?? "" },
    });
    // 成功時は新しいセッション ID が Set-Cookie で返る。そこから sub だけを読む
    const sub = store.get(parseSetCookie(res.headers.get("set-cookie"))?.value)?.user?.sub ?? "";
    note(res.status === 302 ? "login.succeeded" : "login.failed", sub, `callback status ${res.status}`);
    return res;
  });

  // 3. ログアウト。セッション 9 の /logout に任せ、その前後で失効と記録を足す
  app.get("/logout", async (c) => {
    const session = store.get(getCookie(c, SESSION_COOKIE));
    // 消える前に取っておく（消えたあとでは失効を頼めない）
    const refreshToken = session?.tokens?.refreshToken ?? "";
    const sub = session?.user?.sub ?? "";
    const res = await rp.request("/logout", { headers: { cookie: c.req.header("cookie") ?? "" } });
    // 認可サーバー側でもリフレッシュトークンを使えなくする（RFC 7009・セッション 16）
    const revocation = refreshToken === "" ? undefined : await revokeToken(refreshToken, "refresh_token");
    note("logout", sub, "利用者がログアウトしました", { revocationStatus: revocation?.status ?? 0 });
    return res;
  });

  /** api-service の失敗を、利用者に見せる形に翻訳します */
  const translate = async (c: Context, upstream: Response): Promise<Response> => {
    if (upstream.status === 404) {
      // relayStatus() は 404 も 502 にまとめるが、「無い」は利用者に伝える意味がある
      return c.json({ error: "not_found" }, 404);
    }
    if (relayStatus(upstream.status) === 403) {
      const body = (await upstream.json().catch(() => ({}))) as ApiFailure;
      return c.json({ error: "forbidden", message: body.message ?? "" }, 403);
    }
    // 401（こちらのトークンが通らなかった）も 502 にまとめる。利用者の操作では直せない
    return c.json({ error: "api_unavailable" }, 502);
  };

  /**
   * ログイン済みかを確かめ、トークンの関門を通し、api-service を呼びます。
   * アクセストークンが外に出るのはこの関数の中だけです。
   */
  const relay = async (c: Context, path: string): Promise<RelayResult> => {
    const sessionId = getCookie(c, SESSION_COOKIE);
    const session = store.get(sessionId);
    if (session === undefined || session.user === undefined) {
      return { ok: false, res: c.json({ error: "unauthorized" }, 401) };
    }
    const guarded = await guardAccessToken(session, rotation);
    if (guarded.kind === "reuse_detected") {
      // 盗まれた可能性がある。このセッションは落として、もう一度ログインしてもらう
      note("refresh.reuse_detected", session.user.sub, "使用済みのリフレッシュトークンが再び現れました");
      store.destroy(sessionId);
      return { ok: false, res: c.json({ error: "session_revoked" }, 401) };
    }
    if (guarded.kind === "expired") {
      return { ok: false, res: c.json({ error: "session_expired" }, 401) };
    }
    if (guarded.refreshed) {
      note("refresh.rotated", session.user.sub, "アクセストークンを取り直しました");
    }
    const upstream = await callApi(apiFetch, path, guarded.accessToken);
    return upstream.status === 200
      ? { ok: true, upstream, session }
      : { ok: false, res: await translate(c, upstream) };
  };

  // 4. 自分に見える注文の一覧。応答に入れるものを 1 つずつ列挙する（展開しない）
  app.get("/orders", async (c) => {
    const out = await relay(c, "/orders");
    if (!out.ok) {
      return out.res;
    }
    const payload = (await out.upstream.json()) as OrdersPayload;
    return c.json({
      username: out.session.user?.username ?? "",
      roles: payload.roles ?? [],
      count: payload.count ?? 0,
      totalAmount: payload.totalAmount ?? 0,
      orders: payload.orders ?? [],
    });
  });

  // 5. 注文 1 件。403 と 404 はそのままの意味で伝える
  app.get("/orders/:orderId", async (c) => {
    const out = await relay(c, `/orders/${encodeURIComponent(c.req.param("orderId"))}`);
    if (!out.ok) {
      return out.res;
    }
    const payload = (await out.upstream.json()) as { order?: ApiOrder };
    return c.json({ order: payload.order ?? null });
  });

  // 6. 担当店舗の在庫。staff でなければ api-service が 403 を返す
  app.get("/inventory", async (c) => {
    const out = await relay(c, "/inventory");
    if (!out.ok) {
      return out.res;
    }
    const payload = (await out.upstream.json()) as InventoryPayload;
    return c.json({ storeId: payload.storeId ?? "", items: payload.items ?? [] });
  });

  // 残りの経路（/me・/）はセッション 9 の RP に任せる
  app.route("/", rp);
  return { app, store, rotation, audit };
}
