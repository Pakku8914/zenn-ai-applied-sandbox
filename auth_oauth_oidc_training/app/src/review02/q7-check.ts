import { loginHeadless } from "../test-helpers/headless-login.js";
import { readAllOrders } from "./q7-verify-order-read.js";

const alice = await loginHeadless();
const bob = await loginHeadless({ username: "bob", password: "bob-pass" });

const cases: readonly [string, string | undefined, number][] = [
  ["ヘッダ無し", undefined, 401],
  ["Basic スキーム", "Basic YWxpY2U6YWxpY2UtcGFzcw==", 401],
  ["壊れた Bearer", "Bearer あいうえお", 401],
  ["alice の ID トークン", `Bearer ${alice.tokens.id_token ?? ""}`, 401],
  ["alice のアクセストークン", `Bearer ${alice.tokens.access_token}`, 403],
  ["bob のアクセストークン", `Bearer ${bob.tokens.access_token}`, 200],
];

let failed = 0;
for (const [label, header, expected] of cases) {
  const res = await readAllOrders(header);
  const ok = res.status === expected;
  if (!ok) failed += 1;
  const challenge = res.headers["www-authenticate"] ?? "(付けない)";
  console.log(`${ok ? "OK" : "NG"} ${label}: ${res.status}（期待 ${expected}） ${challenge}`);
}
if (failed > 0) process.exit(1);
console.log("すべて期待どおりです");
