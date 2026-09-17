// セッション 9 の練習問題の解答を検証するスクリプト。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。realm の設定は書き換えません。
import { loginHeadless } from "../test-helpers/headless-login.js";
import { reportLogin } from "./rp-q1-login-report.js";
import { runLifetimeExperiments } from "./rp-q4-session-lifetime.js";
import { buildMePayload, containsJwt } from "./rp-q5-me-payload.js";
import { failedNames, verifyIdTokenManually } from "./rp-q6-manual-verify.js";
import { RpSessionStore } from "./rp-session-store.js";
import type { RpSession } from "./rp-session-store.js";
import { createRpApp } from "./rp-server.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 9 練習問題の検証 ===\n");

// 問題 1: /login が「ブラウザに渡したもの」と「サーバー側に控えたもの」
console.log("問題 1: /login の応答");
const store = new RpSessionStore();
const app = await createRpApp({ store });
const report = reportLogin(await app.request("/login"), store);
check("status", report.status, 302);
check("ブラウザに渡したパラメータ", report.browserParams, [
  "client_id",
  "code_challenge",
  "code_challenge_method",
  "nonce",
  "redirect_uri",
  "response_type",
  "scope",
  "state",
]);
check("セッション Cookie", report.cookie, {
  name: "rp_sid",
  valueLength: 43,
  httpOnly: true,
  sameSite: "Lax",
  path: "/",
});
check("サーバー側に控えた値", report.kept, ["code_verifier", "nonce", "state"]);
check("state がブラウザと手元で一致", report.stateMatches, true);

// 問題 4: セッションの 2 本の期限
console.log("\n問題 4: セッションの 2 本の期限");
const experiments = runLifetimeExperiments();
check("アイドル期限（30 分）の生存", experiments[0]?.steps.map((step) => step.alive), [true, true, false]);
check("絶対期限（1 時間）の生存", experiments[1]?.steps.map((step) => step.alive), [true, true, true, false]);

// 問題 5: /me が返すもの
console.log("\n問題 5: /me が返すもの");
const sample: RpSession = {
  createdAt: 0,
  lastSeenAt: 0,
  attempt: undefined,
  user: { sub: "alice-sub", username: "alice", name: "Alice" },
  tokens: {
    accessToken: "eyJhbGciOiJSUzI1NiJ9.(検証用のダミー)",
    refreshToken: "eyJhbGciOiJIUzUxMiJ9.(検証用のダミー)",
    idToken: "eyJhbGciOiJSUzI1NiJ9.(検証用のダミー)",
    accessTokenExpiresAt: 300_000,
  },
};
check("leaky はトークンを含む", containsJwt(buildMePayload(sample, "leaky", 0)), true);
check("safe はトークンを含まない", containsJwt(buildMePayload(sample, "safe", 0)), false);
check("safe が返す残り秒数", buildMePayload(sample, "safe", 0)["accessTokenExpiresIn"], 300);

// 問題 6: ID トークンの自前検証
console.log("\n問題 6: ID トークンの自前検証");
const login = await loginHeadless(); // 検証用ヘルパーにブラウザ役を任せて ID トークンを 1 つ取る
const idToken = login.tokens.id_token ?? "";
const checks = await verifyIdTokenManually(idToken, login.nonce);
check("落ちた検証項目", failedNames(checks), []);
check("検証項目の数", checks.length, 5);
check("nonce を変えると落ちる", failedNames(await verifyIdTokenManually(idToken, "wrong-nonce")), [
  "nonce が送った値と同じ",
]);

console.log(
  failures === 0
    ? "\nセッション 9 の練習問題の検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
