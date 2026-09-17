// 認可コードフロー + PKCE を 1 回通して、要所を表示するデモ。
// ブラウザの操作だけを検証用ヘルパーに肩代わりさせ、それ以外は自分の実装を使います。
import { ISSUER_INTERNAL, ISSUER_PUBLIC } from "./bookstore-client.js";
import { PendingLoginStore } from "./rp-authorize.js";
import { TokenExchangeError, exchangeCodeForTokens } from "./rp-token-exchange.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";

const store = new PendingLoginStore();

// 1. 自分の実装で認可リクエストを組み立てる
const started = store.start(ISSUER_PUBLIC);
const url = new URL(started.authorizationUrl);
console.log("=== 1. 認可リクエストを組み立てる ===");
console.log(`ブラウザに渡す URL のホスト: ${url.host}`);
console.log(`コードから直接叩くときのホスト: ${new URL(ISSUER_INTERNAL).host}`);
for (const key of ["response_type", "client_id", "redirect_uri", "scope", "code_challenge_method"]) {
  console.log(`${key}: ${url.searchParams.get(key)}`);
}
console.log(`state: ${started.state.length} 文字（値は毎回変わるので非表示）`);
console.log(`code_challenge: ${url.searchParams.get("code_challenge")?.length} 文字（S256）`);

// 2. ブラウザ役に alice としてログインしてもらう（本番ではここは人とブラウザの仕事）
console.log("\n=== 2. ブラウザ役にログインしてもらう ===");
const browser = await loginHeadless();
store.remember({ state: browser.state, codeVerifier: browser.codeVerifier });
console.log(`コールバックのクエリ: ${[...browser.callbackParams.keys()].sort().join(", ")}`);
const { code } = store.consumeCallback(browser.callbackParams);
console.log("state の突き合わせ: 成功");

// 3. 交換の結果を見る
console.log("\n=== 3. 受け取ったトークン ===");
console.log(`token_type: ${browser.tokens.token_type}`);
console.log(`expires_in: ${browser.tokens.expires_in}`);
console.log(`scope: ${browser.tokens.scope}`);
const payload = decodeJwtPart<{
  aud: string;
  azp: string;
  realm_access?: { roles: string[] };
}>(browser.tokens.access_token, 1);
console.log(`アクセストークンの aud: ${payload.aud}`);
console.log(`アクセストークンの azp: ${payload.azp}`);
console.log(`ロール: ${(payload.realm_access?.roles ?? []).join(", ")}`);

// 4. 同じ認可コードをもう一度使ってみる（自分の実装で交換を試す）
console.log("\n=== 4. 同じ認可コードをもう一度使う ===");
try {
  await exchangeCodeForTokens({ code, codeVerifier: browser.codeVerifier });
  console.log("2 回目も成功してしまいました（想定外）");
} catch (err) {
  if (!(err instanceof TokenExchangeError)) throw err;
  console.log(`HTTP ${err.status} ${err.error} / ${err.errorDescription}`);
}
