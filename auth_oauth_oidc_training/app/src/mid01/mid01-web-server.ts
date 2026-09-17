// 中間プロジェクト mid01: 書店のフロント（web-app）。RP（リライング・パーティ）とその画面です。
// セッション 9 で作った 3 経路（/login・/callback・/me）に、
// アクセストークンを実際に使う 2 経路（/orders・/orders/:orderId）とログアウトを足したものです。
// トークンは 1 度もブラウザに渡りません。ブラウザが持つのはセッション ID だけです。
import { Hono } from "hono";
import type { Context } from "hono";
import { deleteCookie, getCookie, setCookie } from "hono/cookie";
import * as client from "openid-client";
import { REDIRECT_URI, SCOPE } from "../session06/bookstore-client.js";
import { refreshAccessToken } from "../session07/rp-refresh.js";
import {
  POST_LOGOUT_REDIRECT_URI,
  callbackUrl,
  getOpenIdConfig,
  toBrowserUrl,
} from "../session09/rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "../session09/rp-session-store.js";
import type { LoginAttempt, RpSession } from "../session09/rp-session-store.js";
import { callApi, defaultApiFetch } from "./mid01-api-client.js";
import type { ApiErrorPayload, ApiFetch, ApiOrderPayload, ApiOrdersPayload } from "./mid01-api-client.js";

export type WebAppOptions = {
  store?: RpSessionStore; // セッションの置き場所。渡さなければ新しく作る
  config?: client.Configuration; // discovery の結果。渡さなければ自分で取得する
  apiFetch?: ApiFetch; // api-service への問い合わせ口。検証では app.request を差し込む
  cookieSecure?: boolean; // Cookie に Secure を付けるか（サンドボックスは HTTP なので既定 false）
};

/** 期限の何秒前から取り直すか。通信中に切れるのを避けるための前倒し（セッション 7 と同じ 30 秒） */
const REFRESH_SKEW_SECONDS = 30;

/** ID トークンのクレームは JSON なので、文字列として使う前に型を確かめる */
function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * 認可コードの交換と検証。失敗を例外のまま外に出さず、戻り値で扱えるようにします。
 * openid-client は state・iss・PKCE・ID トークン（nonce を含む）の検証をまとめて行い、
 * 1 つでも通らなければ例外を投げます。
 */
async function grantTokens(config: client.Configuration, currentUrl: URL, attempt: LoginAttempt) {
  try {
    const tokens = await client.authorizationCodeGrant(config, currentUrl, {
      pkceCodeVerifier: attempt.codeVerifier, // PKCE：手元の合鍵を初めてここで出す
      expectedState: attempt.state, // CSRF 対策：自分が始めたログインか
      expectedNonce: attempt.nonce, // リプレイ対策：この ID トークンは今回の応答か
      idTokenExpected: true, // ID トークンが無い応答は認証として扱わない
    });
    return { ok: true as const, tokens };
  } catch (err) {
    return { ok: false as const, message: err instanceof Error ? err.message : String(err) };
  }
}

export async function createWebApp(options: WebAppOptions = {}): Promise<Hono> {
  const config = options.config ?? (await getOpenIdConfig());
  const store = options.store ?? new RpSessionStore();
  const apiFetch = options.apiFetch ?? defaultApiFetch;
  const cookieSecure = options.cookieSecure ?? process.env["RP_COOKIE_SECURE"] === "true";

  const putSessionCookie = (c: Context, id: string): void => {
    setCookie(c, SESSION_COOKIE, id, {
      path: "/",
      httpOnly: true, // JavaScript から読めない（XSS でセッション ID を持ち去られない）
      sameSite: "Lax", // 他サイトから出た POST には付けない
      secure: cookieSecure, // HTTPS 以外では送らない（本番では必ず true）
    });
  };

  /** ログイン済みのセッションだけを取り出します。ここを通らない経路からトークンに触らせません */
  const loggedInSession = (c: Context): RpSession | undefined => {
    const session = store.get(getCookie(c, SESSION_COOKIE));
    return session === undefined || session.user === undefined ? undefined : session;
  };

  /**
   * アクセストークンを使う直前に必ず通す関門。
   * 期限が近ければリフレッシュトークンで取り直し、サーバー側のセッションに入れ直します（セッション 7）。
   * undefined が返ったら、もう一度ログインしてもらうしかありません。
   */
  const freshAccessToken = async (session: RpSession): Promise<string | undefined> => {
    const tokens = session.tokens;
    if (tokens === undefined) {
      return undefined;
    }
    if (Date.now() < tokens.accessTokenExpiresAt - REFRESH_SKEW_SECONDS * 1000) {
      return tokens.accessToken;
    }
    if (tokens.refreshToken === undefined || tokens.refreshToken === "") {
      return undefined;
    }
    try {
      const renewed = await refreshAccessToken({ refreshToken: tokens.refreshToken });
      session.tokens = {
        accessToken: renewed.access_token,
        // 新しいリフレッシュトークンが返らないこともあるので、手元のものを引き継ぐ
        refreshToken: renewed.refresh_token ?? tokens.refreshToken,
        // ID トークンはログアウトの id_token_hint に使うので、返らなければ捨てずに残す
        idToken: renewed.id_token ?? tokens.idToken,
        accessTokenExpiresAt: Date.now() + renewed.expires_in * 1000,
      };
      return renewed.access_token;
    } catch {
      // リフレッシュトークンも切れている／再利用を検知された（セッション 7）
      return undefined;
    }
  };

  /**
   * api-service が返した失敗を、利用者向けの応答に翻訳します。
   * 403（許されない）と 404（無い）はそのままの意味で伝え、
   * 401（自分のトークンが通らなかった）は利用者のせいではないので 502 にします。
   */
  const relayFailure = async (c: Context, res: Response): Promise<Response> => {
    const body = (await res.json().catch(() => ({}))) as ApiErrorPayload;
    if (res.status === 403) {
      return c.json({ error: "forbidden", reason: body.reason ?? "" }, 403);
    }
    if (res.status === 404) {
      return c.json({ error: "not_found" }, 404);
    }
    return c.json({ error: "api_unavailable", detail: body.error ?? `status ${res.status}` }, 502);
  };

  const app = new Hono();
  // 認証に関わる応答はキャッシュさせない。個々のハンドラで付け忘れないよう、
  // 出口で一括して付ける（1 か所にまとめれば、経路を足しても漏れない）
  app.use("*", async (c, next) => {
    await next();
    c.res.headers.set("cache-control", "no-store");
  });

  // 1. ログインを開始する。state・nonce・code_verifier を作り、サーバー側に預けてから転送する
  app.get("/login", async (c) => {
    const codeVerifier = client.randomPKCECodeVerifier();
    const codeChallenge = await client.calculatePKCECodeChallenge(codeVerifier);
    const state = client.randomState();
    const nonce = client.randomNonce();

    const authorizationUrl = client.buildAuthorizationUrl(config, {
      redirect_uri: REDIRECT_URI,
      scope: SCOPE,
      state,
      nonce,
      code_challenge: codeChallenge,
      code_challenge_method: "S256", // plain は使わない（OAuth 2.1 が要求する方式）
    });

    // 合鍵（code_verifier）と照合用の値はサーバー側セッションへ。URL にも Cookie にも入れない
    const { id } = store.startLogin({ state, nonce, codeVerifier });
    putSessionCookie(c, id);
    return c.redirect(toBrowserUrl(authorizationUrl), 302);
  });

  // 2. 認可サーバーからの戻り。ここで初めて「誰か」が確定する
  app.get("/callback", async (c) => {
    const sessionId = getCookie(c, SESSION_COOKIE);
    const attempt = store.get(sessionId)?.attempt;
    if (attempt === undefined) {
      // Cookie が無い／期限切れ。state の持ち主が分からないので、ここで打ち切る
      return c.json({ error: "no_login_in_progress" }, 400);
    }

    const granted = await grantTokens(config, callbackUrl(new URL(c.req.url).search), attempt);
    if (!granted.ok) {
      // 検証に失敗したログインは「途中の状態」を残さず捨てる
      store.destroy(sessionId);
      deleteCookie(c, SESSION_COOKIE, { path: "/" });
      return c.json({ error: "login_failed", detail: granted.message }, 400);
    }

    const claims = granted.tokens.claims();
    if (claims === undefined) {
      return c.json({ error: "id_token_missing" }, 500);
    }

    // ログイン成功。セッション ID を作り直してからトークンを預ける（セッション固定攻撃の対策）
    const rotated = store.completeLogin(sessionId, {
      user: {
        sub: claims.sub, // 画面にも認可にも使う不変の識別子
        username: asString(claims["preferred_username"]),
        name: asString(claims["name"]),
      },
      tokens: {
        accessToken: granted.tokens.access_token,
        refreshToken: granted.tokens.refresh_token,
        idToken: granted.tokens.id_token ?? "",
        accessTokenExpiresAt: Date.now() + (granted.tokens.expires_in ?? 0) * 1000,
      },
    });
    putSessionCookie(c, rotated.id);
    return c.redirect("/orders", 302);
  });

  // 3. ログイン後の画面。トークンは返さず、必要な情報だけを返す
  app.get("/me", (c) => {
    const session = loggedInSession(c);
    if (session === undefined || session.user === undefined) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const expiresAt = session.tokens?.accessTokenExpiresAt ?? 0;
    return c.json({
      user: session.user,
      accessTokenExpiresIn: Math.max(0, Math.round((expiresAt - Date.now()) / 1000)),
    });
  });

  // 4. 自分の注文一覧。預かったアクセストークンを初めて使う経路
  app.get("/orders", async (c) => {
    const session = loggedInSession(c);
    if (session === undefined || session.user === undefined) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const accessToken = await freshAccessToken(session);
    if (accessToken === undefined) {
      return c.json({ error: "session_expired" }, 401);
    }

    const res = await callApi(apiFetch, "/orders", accessToken);
    if (res.status !== 200) {
      return await relayFailure(c, res);
    }
    const payload = (await res.json()) as ApiOrdersPayload;
    // 画面に必要なものだけを返す。アクセストークンは 1 文字も混ぜない
    return c.json({
      username: session.user.username,
      count: payload.count,
      totalAmount: payload.totalAmount,
      orders: payload.orders,
    });
  });

  // 5. 注文 1 件。api-service の 403 / 404 をそのままの意味で伝える
  app.get("/orders/:orderId", async (c) => {
    const session = loggedInSession(c);
    if (session === undefined) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const accessToken = await freshAccessToken(session);
    if (accessToken === undefined) {
      return c.json({ error: "session_expired" }, 401);
    }
    const orderId = c.req.param("orderId");
    const res = await callApi(apiFetch, `/orders/${encodeURIComponent(orderId)}`, accessToken);
    if (res.status !== 200) {
      return await relayFailure(c, res);
    }
    const payload = (await res.json()) as ApiOrderPayload;
    return c.json(payload);
  });

  // 6. ログアウト。アプリのセッションを消し、認可サーバーにもログアウトを伝える
  app.get("/logout", (c) => {
    const sessionId = getCookie(c, SESSION_COOKIE);
    const idToken = store.get(sessionId)?.tokens?.idToken;
    store.destroy(sessionId); // まずアプリ側を消す（預かったトークンもここで消える）
    deleteCookie(c, SESSION_COOKIE, { path: "/" });

    if (idToken === undefined || idToken === "") {
      return c.redirect("/", 302); // ログインしていなかった場合は伝えることが無い
    }
    const endSessionUrl = client.buildEndSessionUrl(config, {
      id_token_hint: idToken, // どのセッションを終わらせるかを示す
      post_logout_redirect_uri: POST_LOGOUT_REDIRECT_URI,
    });
    return c.redirect(toBrowserUrl(endSessionUrl), 302);
  });

  // 7. トップ。ログアウト後にブラウザが戻ってくる先
  app.get("/", (c) => {
    const session = store.get(getCookie(c, SESSION_COOKIE));
    return c.json({ loggedIn: session?.user !== undefined, username: session?.user?.username ?? null });
  });

  return app;
}
