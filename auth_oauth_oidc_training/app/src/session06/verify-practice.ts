// セッション 6 の練習問題の解答（問題 1〜5）の自己検証。
// 問題 6 はブラウザでの操作が必要なため、ここでは検証しません。
import { ISSUER_INTERNAL, REDIRECT_URI } from "./bookstore-client.js";
import { buildAuthorizeReport } from "./rp-q1-authorize-report.js";
import { buildPkceCheckReport } from "./rp-q2-pkce-check.js";
import { collectErrorMatrix } from "./rp-q3-error-matrix.js";
import { runCallbackDrill } from "./rp-q4-callback-guard.js";
import { demonstrateOneTimeCode } from "./rp-q5-one-time-code.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}`);
  if (!ok) {
    console.log(`     実際:   ${JSON.stringify(actual)}`);
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

// 問題 1: 認可リクエストの点検レポート
check("問題 1 のレポート", buildAuthorizeReport(), [
  "=== 認可リクエストの点検 ===",
  "ブラウザに渡す URL のホスト: localhost:8080",
  "コードから叩く URL のホスト: keycloak:8080",
  "response_type: code",
  "client_id: web-app",
  `redirect_uri: ${REDIRECT_URI}`,
  "scope: openid profile email",
  "state: 22 文字（値は毎回変わるので非表示）",
  "code_challenge: 43 文字（値は毎回変わるので非表示）",
  "code_challenge_method: S256",
  "code_challenge を手元の code_verifier から再計算できる: true",
]);

// 問題 2: PKCE の対応づけ
check("問題 2 のレポート", buildPkceCheckReport(), [
  "=== PKCE の対応づけの点検 ===",
  "RFC 7636 の検証用データ: 一致",
  "100 組すべてで code_verifier が 43 文字: true",
  "100 組すべてで Base64URL の文字だけ: true",
  "100 組すべてで code_challenge を再計算できる: true",
  "重複した code_verifier の数: 0",
  "verifier を 1 文字変えると challenge も変わる: true",
]);

// 問題 3: 間違えたときの応答の一覧
const matrix = await collectErrorMatrix();
check(
  "問題 3 の一覧（試したこと・status・error）",
  matrix.map((row) => [row.label, row.status, row.error]),
  [
    ["正しいリクエスト", 200, "-"],
    ["code_challenge_method=plain", 302, "invalid_request"],
    ["PKCE のパラメータなし", 302, "invalid_request"],
    ["未登録の redirect_uri", 400, "-"],
    ["response_type=token（implicit）", 302, "unauthorized_client"],
  ],
);
check(
  "問題 3: implicit のエラーだけフラグメントで返る",
  matrix.filter((row) => row.place === "fragment").map((row) => row.label),
  ["response_type=token（implicit）"],
);

// 問題 4: コールバックの判定
check("問題 4 のドリル", runCallbackDrill(), [
  "=== コールバックの判定ドリル ===",
  "1. 自分が始めたログイン: 受理",
  "2. 同じコールバックの 2 回目: state 不一致",
  "3. state が無い: state 不一致",
  "4. 知らない state: state 不一致",
  "5. state は一致するが code が無い: 認可コードなし",
  "6. error 付きで戻ってきた: 認可サーバーのエラー",
  "保管に残っている未完了ログイン: 1 件",
]);

// 問題 5: 認可コードの使い捨て
check("問題 5 のレポート", await demonstrateOneTimeCode(), [
  "=== 認可コードの使い捨てを確かめる ===",
  "1 回目の交換: token_type=Bearer expires_in=300",
  `コールバックに付いてきた iss: ${ISSUER_INTERNAL}`,
  "2 回目の交換: HTTP 400 invalid_grant / Code not valid",
  "1 回目のアクセストークンの azp: web-app",
  "1 回目のアクセストークンの有効期間: 300 秒",
]);

console.log(
  failures === 0
    ? "\nセッション 6 の練習問題（1〜5）の検証にすべて成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
