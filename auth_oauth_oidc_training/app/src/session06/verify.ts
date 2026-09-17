// セッション 6 の自己検証スクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了するため、人が出力を読んで判断する必要はありません。
// realm の設定は一切書き換えません（設定を変える実験は admin-pkce-experiment.ts が担当）。
import { ISSUER_INTERNAL, ISSUER_PUBLIC, REDIRECT_URI } from "./bookstore-client.js";
import { PendingLoginStore, buildAuthorizationUrl, probeAuthorizationRequest } from "./rp-authorize.js";
import { challengeFor, createPkcePair } from "./rp-pkce.js";
import { TokenExchangeError, exchangeCodeForTokens } from "./rp-token-exchange.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 同期処理が投げた例外のメッセージを返します */
function rejectedBy(run: () => unknown): string {
  try {
    run();
    return "例外になりませんでした";
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

/** トークン交換の失敗を、認可サーバーが返した形のまま取り出します */
async function exchangeFailure(
  run: () => Promise<unknown>,
): Promise<{ status: number; error: string; description: string }> {
  try {
    await run();
    return { status: 0, error: "交換が成功してしまいました", description: "" };
  } catch (err) {
    if (err instanceof TokenExchangeError) {
      return { status: err.status, error: err.error, description: err.errorDescription };
    }
    return { status: -1, error: err instanceof Error ? err.message : String(err), description: "" };
  }
}

// 1. PKCE の対応づけ（RFC 7636 Appendix B の検証用データで実装の正しさを確かめる）
check(
  "RFC 7636 の検証用データと一致する",
  challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
  "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
);
const pkce = createPkcePair();
check("code_verifier の長さ", pkce.codeVerifier.length, 43);
check("code_verifier は Base64URL の文字だけ", /^[A-Za-z0-9\-._~]+$/.test(pkce.codeVerifier), true);
check("code_challenge の長さ", pkce.codeChallenge.length, 43);
check("code_challenge は code_verifier から再計算できる", challengeFor(pkce.codeVerifier), pkce.codeChallenge);
check("呼ぶたびに違う code_verifier になる", createPkcePair().codeVerifier === pkce.codeVerifier, false);

// 2. 認可リクエストの組み立て
const store = new PendingLoginStore();
const started = store.start(ISSUER_PUBLIC);
const url = new URL(started.authorizationUrl);
check("ブラウザに渡す URL のホスト", url.host, "localhost:8080");
check("認可エンドポイントのパス", url.pathname, "/realms/bookstore/protocol/openid-connect/auth");
check("パラメータの名前（並べ替え）", [...url.searchParams.keys()].sort(), [
  "client_id",
  "code_challenge",
  "code_challenge_method",
  "redirect_uri",
  "response_type",
  "scope",
  "state",
]);
check("response_type", url.searchParams.get("response_type"), "code");
check("client_id", url.searchParams.get("client_id"), "web-app");
check("redirect_uri", url.searchParams.get("redirect_uri"), REDIRECT_URI);
check("scope", url.searchParams.get("scope"), "openid profile email");
check("code_challenge_method", url.searchParams.get("code_challenge_method"), "S256");
check(
  "URL の code_challenge は手元の code_verifier に対応している",
  url.searchParams.get("code_challenge"),
  challengeFor(started.codeVerifier),
);

// 3. ISSUER_PUBLIC と ISSUER_INTERNAL の非対称（ブラウザ向けの URL はコンテナからは届かない）
let publicFetchFailed = false;
try {
  await fetch(started.authorizationUrl, { redirect: "manual" });
} catch {
  publicFetchFailed = true;
}
check("ブラウザ向けの URL はコンテナ内からは届かない", publicFetchFailed, true);

const internal = store.start(ISSUER_INTERNAL);
check("コンテナ内から叩く URL のホスト", new URL(internal.authorizationUrl).host, "keycloak:8080");
const authRes = await fetch(internal.authorizationUrl, { redirect: "manual" });
const authHtml = await authRes.text();
check("認可リクエストの応答", authRes.status, 200);
check("ログイン画面が返ってきている", authHtml.includes('id="kc-form-login"'), true);
check(
  "受け取った Cookie の名前（並べ替え）",
  authRes.headers.getSetCookie().map((raw) => raw.split("=")[0] ?? "").sort(),
  ["AUTH_SESSION_ID", "KC_AUTH_SESSION_HASH", "KC_RESTART"],
);

// 4. パラメータを間違えたときに認可サーバーが返すもの
const pair = createPkcePair();
const okOutcome = await probeAuthorizationRequest(
  buildAuthorizationUrl({ issuer: ISSUER_INTERNAL, state: "s-ok", codeChallenge: pair.codeChallenge }),
);
check("正しいリクエストの結果", okOutcome.result, "ログイン画面");

const plainOutcome = await probeAuthorizationRequest(
  buildAuthorizationUrl({
    issuer: ISSUER_INTERNAL,
    state: "s-plain",
    codeChallenge: pair.codeVerifier, // plain では challenge と verifier が同じ値になる
    override: { code_challenge_method: "plain" },
  }),
);
check("plain を要求したときの結果", plainOutcome, {
  status: 302,
  result: "エラーでリダイレクト",
  error: "invalid_request",
  description: "Invalid parameter: code challenge method is not matching the configured one",
  place: "query",
});

const noPkceOutcome = await probeAuthorizationRequest(
  buildAuthorizationUrl({
    issuer: ISSUER_INTERNAL,
    state: "s-nopkce",
    codeChallenge: pair.codeChallenge,
    override: { code_challenge: null, code_challenge_method: null },
  }),
);
check("PKCE を付けなかったときの結果", noPkceOutcome, {
  status: 302,
  result: "エラーでリダイレクト",
  error: "invalid_request",
  description: "Missing parameter: code_challenge_method",
  place: "query",
});

const badRedirectOutcome = await probeAuthorizationRequest(
  buildAuthorizationUrl({
    issuer: ISSUER_INTERNAL,
    state: "s-bad-redirect",
    codeChallenge: pair.codeChallenge,
    redirectUri: "http://evil.example.com/callback",
  }),
);
check("未登録の redirect_uri は 400 のエラーページ", badRedirectOutcome.status, 400);
check("未登録の redirect_uri ではリダイレクトしない", badRedirectOutcome.result, "エラーページ");

const implicitOutcome = await probeAuthorizationRequest(
  buildAuthorizationUrl({
    issuer: ISSUER_INTERNAL,
    state: "s-implicit",
    codeChallenge: pair.codeChallenge,
    override: { response_type: "token" },
  }),
);
check("implicit を試したときの status", implicitOutcome.status, 302);
check("implicit を試したときの error", implicitOutcome.error, "unauthorized_client");
check("implicit のエラーはフラグメントで返る", implicitOutcome.place, "fragment");

// 5. state の突き合わせ（CSRF 対策）
const csrfStore = new PendingLoginStore();
const mine = csrfStore.start(ISSUER_INTERNAL);
check(
  "知らない state のコールバックは拒否する",
  rejectedBy(() =>
    csrfStore.consumeCallback(new URLSearchParams({ state: "attacker-state", code: "attacker-code" })),
  ),
  "state が一致しません（自分が始めたログインではありません）",
);
const myCallback = new URLSearchParams({ state: mine.state, code: "code-1234", iss: ISSUER_INTERNAL });
check(
  "自分が始めたログインなら認可コードを取り出せる",
  csrfStore.consumeCallback(myCallback).code,
  "code-1234",
);
check(
  "同じコールバックは 2 回処理できない",
  rejectedBy(() => csrfStore.consumeCallback(myCallback)),
  "state が一致しません（自分が始めたログインではありません）",
);
check("処理し終わった state は残らない", csrfStore.size, 0);
check(
  "error 付きのコールバックは state より先に弾く",
  rejectedBy(() =>
    csrfStore.consumeCallback(
      new URLSearchParams({ error: "access_denied", error_description: "拒否されました", state: "x" }),
    ),
  ),
  "認可サーバーがエラーを返しました: access_denied / 拒否されました",
);

// 6. 認可コードフローを完走する（ブラウザ操作だけを検証用ヘルパーに任せる）
const browser = await loginHeadless();
check(
  "コールバックのクエリ（並べ替え）",
  [...browser.callbackParams.keys()].sort(),
  ["code", "iss", "session_state", "state"],
);
check("コールバックの iss", browser.callbackParams.get("iss"), ISSUER_INTERNAL);
check("コールバックの state は送った値と同じ", browser.callbackParams.get("state"), browser.state);
check("トークンレスポンスのキー（並べ替え）", Object.keys(browser.tokens).sort(), [
  "access_token",
  "expires_in",
  "id_token",
  "not-before-policy",
  "refresh_expires_in",
  "refresh_token",
  "scope",
  "session_state",
  "token_type",
]);
check("token_type", browser.tokens.token_type, "Bearer");
check("expires_in", browser.tokens.expires_in, 300);
check("refresh_expires_in", browser.tokens.refresh_expires_in, 1800);
check("scope", browser.tokens.scope, "openid email profile");

const header = decodeJwtPart<Record<string, unknown>>(browser.tokens.access_token, 0);
const payload = decodeJwtPart<Record<string, unknown>>(browser.tokens.access_token, 1);
check("アクセストークンの署名アルゴリズム", header["alg"], "RS256");
check("アクセストークンの iss", payload["iss"], ISSUER_INTERNAL);
check("アクセストークンの aud", payload["aud"], "api-service");
check("アクセストークンの azp", payload["azp"], "web-app");
check("alice のロール", (payload["realm_access"] as { roles?: string[] } | undefined)?.roles, ["customer"]);

// 7. 認可コードは使い捨て（自分の実装で 2 回目の交換を試す）
const flow = new PendingLoginStore();
flow.remember({ state: browser.state, codeVerifier: browser.codeVerifier });
const consumed = flow.consumeCallback(browser.callbackParams);
check(
  "自分の実装でも state を突き合わせて認可コードを取り出せる",
  consumed.code,
  browser.callbackParams.get("code"),
);
const reuse = await exchangeFailure(() =>
  exchangeCodeForTokens({ code: consumed.code, codeVerifier: consumed.codeVerifier }),
);
check("使用済みの認可コードでの交換", reuse, {
  status: 400,
  error: "invalid_grant",
  description: "Code not valid",
});

// 8. discovery の申告と、クライアントに実際に許されていることの差
const discovery = (await (
  await fetch(`${ISSUER_INTERNAL}/.well-known/openid-configuration`)
).json()) as { code_challenge_methods_supported?: string[] };
check(
  "discovery が申告する code_challenge_methods_supported",
  discovery.code_challenge_methods_supported,
  ["plain", "S256"],
);
check(
  "申告には plain があるのに web-app では拒否された",
  discovery.code_challenge_methods_supported?.includes("plain") === true && plainOutcome.error === "invalid_request",
  true,
);

console.log(
  failures === 0
    ? "\nセッション 6 のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
