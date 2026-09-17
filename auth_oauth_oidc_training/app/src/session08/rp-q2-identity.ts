// 練習問題 2 の解答。ID トークンを検証して Identity を組み立て、受け入れてはいけない場合も並べます。
import { IdTokenError, verifyIdToken } from "./rp-verify-id-token.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

/** 検証が拒否した理由を 1 行で返します（通ってしまったらそれも分かるようにします） */
async function reasonOf(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
    return "拒否されませんでした（実装を見直してください）";
  } catch (err) {
    return err instanceof IdTokenError ? err.reason : String(err);
  }
}

const { tokens, nonce } = await loginHeadless(); // 既定は alice
const idToken = tokens.id_token ?? "";

console.log("=== 検証が通ったときに手に入る情報 ===");
const identity = await verifyIdToken({ idToken, expectedNonce: nonce });
console.log(`sub: ${identity.subject === "" ? "（無し）" : "取得できた（値は環境ごとに変わります）"}`);
console.log(`username: ${identity.username}`);
console.log(`name: ${identity.name}`);
console.log(`email: ${identity.email}（確認済み: ${identity.emailVerified}）`);
console.log(`auth_time / sid: ${identity.authTime > 0 ? "あり" : "なし"} / ${identity.sessionId !== "" ? "あり" : "なし"}`);

console.log("\n=== 受け入れてはいけない場合 ===");
console.log(`nonce を 1 文字変える: ${await reasonOf(() => verifyIdToken({ idToken, expectedNonce: `${nonce}x` }))}`);
console.log(`保存した nonce が空: ${await reasonOf(() => verifyIdToken({ idToken, expectedNonce: "" }))}`);
console.log(
  `アクセストークンを渡す: ${await reasonOf(() =>
    verifyIdToken({ idToken: tokens.access_token, expectedNonce: nonce }),
  )}`,
);
console.log(
  `壊れた文字列を渡す: ${await reasonOf(() => verifyIdToken({ idToken: "not-a-jwt", expectedNonce: nonce }))}`,
);
