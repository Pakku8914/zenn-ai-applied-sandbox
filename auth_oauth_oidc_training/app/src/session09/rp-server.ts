// 書店 web-app の RP（リライング・パーティ）本体。
// 中心は 3 経路: /login（認可リクエストの開始）・/callback（コールバック）・/me（セッション確立後の画面）。
// これに /logout（RP-initiated logout）と /（ログアウト後の戻り先）を足した 5 つだけです。
// トークンは 1 度もブラウザに渡りません。ブラウザが持つのはセッション ID だけです。
import { Hono } from "hono";
import type { Context } from "hono";
import { deleteCookie, getCookie, setCookie } from "hono/cookie";
import * as client from "openid-client";
import { REDIRECT_URI, SCOPE } from "../session06/bookstore-client.js";
import { POST_LOGOUT_REDIRECT_URI, callbackUrl, getOpenIdConfig, toBrowserUrl } from "./rp-openid-config.js";
import { RpSessionStore, SESSION_COOKIE } from "./rp-session-store.js";
import type { LoginAttempt } from "./rp-session-store.js";

export type RpOptions = {
  store?: RpSessionStore; // セッションの置き場所。渡さなければ新しく作る
  config?: client.Configuration; // discovery の結果。渡さなければ自分で取得する
  cookieSecure?: boolean; // Cookie に Secure を付けるか（サンドボックスは HTTP なので既定 false）
};

/** ID トークンのクレームは JSON なので、文字列として使う前に型を確かめる */
function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * 認可コードの交換と検証。失敗を例外のまま外に出さず、戻り値で扱えるようにします。
 * openid-client は state・iss・PKCE・ID トークンの検証をまとめて行い、1 つでも通らなければ例外を投げます。
 */
async function grantTokens(config: client.Configuration, currentUrl: URL, attempt: LoginAttempt) {
  try {
    const tokens = await client.authorizationCodeGrant(config, currentUrl, {
      pkceCodeVerifier: attempt.codeVerifier,
      expectedState: attempt.state,
      expectedNonce: attempt.nonce,
      idTokenExpected: true, // ID トークンが無い応答は認証として扱わない
    });
    return { ok: true as const, tokens };
  } catch (err) {
    return { ok: false as const, message: err instanceof Error ? err.message : String(err) };
  }
}

export async function createRpApp(options: RpOptions = {}): Promise<Hono> {
  const config = options.config ?? (await getOpenIdConfig());
  const store = options.store ?? new RpSessionStore();
  const cookieSecure = options.cookieSecure ?? process.env["RP_COOKIE_SECURE"] === "true";

  const putSessionCookie = (c: Context, id: string): void => {
    setCookie(c, SESSION_COOKIE, id, {
      path: "/",
      httpOnly: true, // JavaScript から読めない（XSS でセッション ID を持ち去られない）
      sameSite: "Lax", // 他サイトから出た POST には付けない
      secure: cookieSecure, // HTTPS 以外では送らない（本番では必ず true）
    });
  };

  const app = new Hono();

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
      code_challenge_method: "S256", // plain は使わない
    });

    // 始めたログインは Cookie で紐づいたサーバー側セッションに預ける（ブラウザには渡さない）
    const { id } = store.startLogin({ state, nonce, codeVerifier });
    putSessionCookie(c, id);
    c.header("cache-control", "no-store");
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

    // state・iss・PKCE・ID トークンの検証をまとめて openid-client に任せる
    const granted = await grantTokens(config, callbackUrl(new URL(c.req.url).search), attempt);
    if (!granted.ok) {
      // 検証に失敗したログインは「途中の状態」を残さず捨てる
      store.destroy(sessionId);
      deleteCookie(c, SESSION_COOKIE, { path: "/" });
      return c.json({ error: "login_failed", detail: granted.message }, 400);
    }

    const tokens = granted.tokens;
    const claims = tokens.claims();
    if (claims === undefined) {
      return c.json({ error: "id_token_missing" }, 500);
    }

    // ログイン成功。セッション ID を作り直してからトークンを預ける
    const rotated = store.completeLogin(sessionId, {
      user: { sub: claims.sub, username: asString(claims["preferred_username"]), name: asString(claims["name"]) },
      tokens: {
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
        idToken: tokens.id_token ?? "",
        accessTokenExpiresAt: Date.now() + (tokens.expires_in ?? 0) * 1000,
      },
    });
    putSessionCookie(c, rotated.id);
    c.header("cache-control", "no-store");
    return c.redirect("/me", 302);
  });

  // 3. ログイン後の画面。トークンは返さず、必要な情報だけを返す
  app.get("/me", (c) => {
    const session = store.get(getCookie(c, SESSION_COOKIE));
    if (session === undefined || session.user === undefined) {
      return c.json({ error: "unauthorized" }, 401);
    }
    const expiresAt = session.tokens?.accessTokenExpiresAt ?? 0;
    c.header("cache-control", "no-store");
    return c.json({
      user: session.user,
      // 残り秒数だけを見せる。アクセストークン本体はサーバー側に置いたまま
      accessTokenExpiresIn: Math.max(0, Math.round((expiresAt - Date.now()) / 1000)),
    });
  });

  // 4. ログアウト。アプリのセッションを消し、認可サーバーにもログアウトを伝える
  app.get("/logout", (c) => {
    const sessionId = getCookie(c, SESSION_COOKIE);
    const idToken = store.get(sessionId)?.tokens?.idToken;
    store.destroy(sessionId); // まずアプリ側を消す（トークンもここで消える）
    deleteCookie(c, SESSION_COOKIE, { path: "/" });
    c.header("cache-control", "no-store");

    if (idToken === undefined || idToken === "") {
      // ログインしていなかった場合は認可サーバーに伝えることが無い
      return c.redirect("/", 302);
    }
    const endSessionUrl = client.buildEndSessionUrl(config, {
      id_token_hint: idToken, // どのセッションを終わらせるかを示す（確認画面が出なくなる）
      post_logout_redirect_uri: POST_LOGOUT_REDIRECT_URI,
    });
    return c.redirect(toBrowserUrl(endSessionUrl), 302);
  });

  // 5. トップ。ログアウト後にブラウザが戻ってくる先
  app.get("/", (c) => {
    const session = store.get(getCookie(c, SESSION_COOKIE));
    return c.json({ loggedIn: session?.user !== undefined, username: session?.user?.username ?? null });
  });

  return app;
}
