// 練習問題 5 の解答。nonce を保存して使い捨てにし、ID トークンの使い回しを拒否します。
import { IdTokenError, verifyIdToken } from "./rp-verify-id-token.js";
import { PendingLoginStore } from "./rp-pending-login.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

/** 検証の結果を 1 行で表します */
async function outcome(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
    return "受け入れた";
  } catch (err) {
    return `拒否（${err instanceof IdTokenError ? err.reason : String(err)}）`;
  }
}

console.log("=== 1. 保存と使い捨て（ネットワークを使わない確認） ===");
const store = new PendingLoginStore();
const pending = store.start("dummy-code-verifier");
console.log(`state と nonce は別の値: ${pending.state !== pending.nonce}`);
console.log(`1 回目の取り出しで nonce が一致: ${store.consume(pending.state).nonce === pending.nonce}`);
try {
  store.consume(pending.state);
  console.log("2 回目も取り出せてしまいました（実装を見直してください）");
} catch (err) {
  console.log(`2 回目の取り出し: ${err instanceof Error ? err.message : String(err)}`);
}

console.log("\n=== 2. 別のログインの ID トークンを持ち込む ===");
const loginA = await loginHeadless();
const loginB = await loginHeadless();
const idTokenA = loginA.tokens.id_token ?? "";
console.log(`A の nonce で A の ID トークンを検証: ${await outcome(() => verifyIdToken({ idToken: idTokenA, expectedNonce: loginA.nonce }))}`);
console.log(`B の nonce で A の ID トークンを検証: ${await outcome(() => verifyIdToken({ idToken: idTokenA, expectedNonce: loginB.nonce }))}`);
