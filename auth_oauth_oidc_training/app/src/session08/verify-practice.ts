// 練習問題の解答コードを検証します（問題7 は本文の実装と同じ結果になることを確かめます）。
import { loginHeadless } from "../test-helpers/headless-login.js";
import { IdTokenError, verifyIdToken } from "./rp-verify-id-token.js";
import { manualVerifyIdToken } from "./rp-q7-manual-verify.js";

let failures = 0;
const check = (label: string, actual: unknown, expected: unknown): void => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures += 1;
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
};

/** 本文の実装を「成功なら sub、失敗なら理由」の形にそろえます（比較のため） */
async function reference(idToken: string, expectedNonce: string): Promise<string> {
  try {
    const identity = await verifyIdToken({ idToken, expectedNonce });
    return identity.subject;
  } catch (err) {
    return err instanceof IdTokenError ? err.reason : String(err);
  }
}

const manual = async (idToken: string, expectedNonce: string): Promise<string> => {
  const result = await manualVerifyIdToken({ idToken, expectedNonce });
  return result.ok ? result.subject : result.reason;
};

console.log("=== セッション 8 の練習問題の検証 ===\n");
const { tokens, nonce } = await loginHeadless();
const idToken = tokens.id_token ?? "";

console.log("問題7: 自分で書いた検証が本文の実装と一致するか");
const cases: ReadonlyArray<{ label: string; token: string; nonce: string }> = [
  { label: "正しい ID トークンと正しい nonce", token: idToken, nonce },
  { label: "nonce が一致しない", token: idToken, nonce: "not-the-saved-one" },
  { label: "nonce を保存していない", token: idToken, nonce: "" },
  { label: "ID トークンの代わりにアクセストークンを渡す", token: tokens.access_token, nonce },
  { label: "壊れた文字列を渡す", token: "not.a.jwt", nonce },
];
for (const c of cases) {
  const [mine, theirs] = await Promise.all([manual(c.token, c.nonce), reference(c.token, c.nonce)]);
  check(c.label, mine, theirs);
}

console.log(
  failures === 0
    ? "\nセッション 8 の練習問題の検証にすべて成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
if (failures > 0) process.exit(1);
