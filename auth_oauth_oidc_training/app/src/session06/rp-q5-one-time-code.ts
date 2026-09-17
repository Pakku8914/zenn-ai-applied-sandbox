// 練習問題 5: 認可コードが使い捨てであることを確かめる。
import { PendingLoginStore } from "./rp-authorize.js";
import { TokenExchangeError, exchangeCodeForTokens } from "./rp-token-exchange.js";
import { decodeJwtPart, loginHeadless } from "../test-helpers/headless-login.js";

export async function demonstrateOneTimeCode(): Promise<string[]> {
  const lines = ["=== 認可コードの使い捨てを確かめる ==="];

  // ブラウザ役にログインしてもらう。この時点で 1 回目の交換は済んでいる
  const browser = await loginHeadless();
  const store = new PendingLoginStore();
  store.remember({ state: browser.state, codeVerifier: browser.codeVerifier });
  const { code, codeVerifier } = store.consumeCallback(browser.callbackParams);

  lines.push(
    `1 回目の交換: token_type=${browser.tokens.token_type} expires_in=${browser.tokens.expires_in}`,
  );
  lines.push(`コールバックに付いてきた iss: ${browser.callbackParams.get("iss")}`);

  try {
    await exchangeCodeForTokens({ code, codeVerifier });
    lines.push("2 回目の交換: 成功してしまいました（想定外）");
  } catch (err) {
    if (!(err instanceof TokenExchangeError)) throw err;
    lines.push(`2 回目の交換: HTTP ${err.status} ${err.error} / ${err.errorDescription}`);
  }

  // 2 回目が失敗しても、1 回目に受け取ったトークンはそのまま使えます
  const payload = decodeJwtPart<{ azp: string; exp: number; iat: number }>(
    browser.tokens.access_token,
    1,
  );
  lines.push(`1 回目のアクセストークンの azp: ${payload.azp}`);
  lines.push(`1 回目のアクセストークンの有効期間: ${payload.exp - payload.iat} 秒`);
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q5-one-time-code"))) {
  for (const line of await demonstrateOneTimeCode()) console.log(line);
}
