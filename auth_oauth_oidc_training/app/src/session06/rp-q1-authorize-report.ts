// 練習問題 1: 認可リクエストの点検レポート。
import { ISSUER_INTERNAL, ISSUER_PUBLIC } from "./bookstore-client.js";
import { PendingLoginStore } from "./rp-authorize.js";
import { challengeFor } from "./rp-pkce.js";

export function buildAuthorizeReport(): string[] {
  const store = new PendingLoginStore();
  const started = store.start(ISSUER_PUBLIC);
  const url = new URL(started.authorizationUrl);
  // パラメータが無いことと、空文字であることを区別できるようにします
  const get = (key: string): string => url.searchParams.get(key) ?? "(なし)";

  return [
    "=== 認可リクエストの点検 ===",
    `ブラウザに渡す URL のホスト: ${url.host}`,
    `コードから叩く URL のホスト: ${new URL(ISSUER_INTERNAL).host}`,
    `response_type: ${get("response_type")}`,
    `client_id: ${get("client_id")}`,
    `redirect_uri: ${get("redirect_uri")}`,
    `scope: ${get("scope")}`,
    `state: ${get("state").length} 文字（値は毎回変わるので非表示）`,
    `code_challenge: ${get("code_challenge").length} 文字（値は毎回変わるので非表示）`,
    `code_challenge_method: ${get("code_challenge_method")}`,
    `code_challenge を手元の code_verifier から再計算できる: ${
      get("code_challenge") === challengeFor(started.codeVerifier)
    }`,
  ];
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q1-authorize-report"))) {
  for (const line of buildAuthorizeReport()) console.log(line);
}
