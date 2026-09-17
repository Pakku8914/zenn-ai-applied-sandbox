// セッション 11 の練習問題の解答を検証するスクリプト。
// 判定はすべて手で組んだ材料で動くので、認可サーバーへの通信はありません。
// realm の設定も書き換えません。期待値と一致しなければ非 0 で終了します。
import type { Action } from "../session02/api-authz-decide.js";
import type { TokenFacts } from "./api-authz-claims.js";
import { BookstoreDirectory } from "./api-authz-directory.js";
import { NO_SCOPE_REQUIRED } from "./api-authz-policy.js";
import { evaluateCases, toMarkdown } from "./api-q1-scope-role-matrix.js";
import type { MatrixCase } from "./api-q1-scope-role-matrix.js";
import { applicableGrants, authorizeWithClientRoles } from "./api-q2-client-role-policy.js";
import { MigratingDirectory, judgeMigration } from "./api-q4-owner-migration.js";
import { RevocationLog, gate } from "./api-q5-revocation.js";
import { RULES, buildCases, compare, evaluate, findRule } from "./api-q6-policy-table.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

/** 検証用の判断材料。既定は orders:read / orders:write の両方を要求したクライアント */
const factsFor = (over: Partial<TokenFacts>): TokenFacts => ({
  sub: "sub-unknown",
  username: "unknown",
  scopes: ["openid", "orders:read", "orders:write"],
  realmRoles: ["customer"],
  clientRoles: [],
  issuedAt: 1_000,
  expiresAt: 1_300,
  ...over,
});

console.log("=== セッション 11 練習問題の検証 ===\n");

// 問題 1: スコープとロールの掛け算
console.log("問題 1: スコープとロールの掛け算");
const matrixDir = new BookstoreDirectory();
matrixDir.linkAccount("sub-alice", "alice");
matrixDir.linkAccount("sub-bob", "bob", { storeId: "shinjuku" });

const q1Cases: readonly MatrixCase[] = [
  {
    label: "alice が自分の注文を読む",
    sub: "sub-alice",
    username: "alice",
    scopes: ["openid", "orders:read"],
    realmRoles: ["customer"],
    action: "read",
    orderId: "order-1001",
  },
  {
    label: "alice が自分の注文を読む（orders:read を要求していない）",
    sub: "sub-alice",
    username: "alice",
    scopes: ["openid"],
    realmRoles: ["customer"],
    action: "read",
    orderId: "order-1001",
  },
  {
    label: "alice が他人の注文を読む",
    sub: "sub-alice",
    username: "alice",
    scopes: ["openid", "orders:read"],
    realmRoles: ["customer"],
    action: "read",
    orderId: "order-2001",
  },
  {
    label: "bob が担当店舗の取り消し済み注文を返金する",
    sub: "sub-bob",
    username: "bob",
    scopes: ["openid", "orders:write"],
    realmRoles: ["customer", "staff"],
    action: "refund",
    orderId: "order-1003",
  },
  {
    label: "bob が返金する（orders:write を要求していない）",
    sub: "sub-bob",
    username: "bob",
    scopes: ["openid", "orders:read"],
    realmRoles: ["customer", "staff"],
    action: "refund",
    orderId: "order-1003",
  },
  {
    label: "スコープを強制しない設定で alice が自分の注文を読む",
    sub: "sub-alice",
    username: "alice",
    scopes: ["openid"],
    realmRoles: ["customer"],
    action: "read",
    orderId: "order-1001",
    requiredScopes: NO_SCOPE_REQUIRED,
  },
];

const rows = evaluateCases(q1Cases, matrixDir);
check("ケース数", rows.length, 6);
check(
  "判定の並び",
  rows.map((row) => `${row.httpStatus}/${row.error === "" ? "-" : row.error}/${row.stage}`),
  [
    "200/-/granted",
    "403/insufficient_scope/scope",
    "403/forbidden/subject",
    "200/-/granted",
    "403/insufficient_scope/scope",
    "200/-/granted",
  ],
);
check(
  "足りないスコープ",
  rows.map((row) => row.missing.join(" ")),
  ["", "orders:read", "", "", "orders:write", ""],
);
check("Markdown の表の行数（見出し 2 行 + 6 行）", toMarkdown(rows).split("\n").length, 8);

// 問題 2: クライアントロールで判定する
console.log("\n問題 2: クライアントロールで判定する");
const q2Dir = new BookstoreDirectory();
q2Dir.linkAccount("sub-alice", "alice");
q2Dir.linkAccount("sub-bob", "bob", { storeId: "shinjuku" });
q2Dir.linkAccount("sub-dave", "dave"); // 担当店舗は登録していない
q2Dir.linkAccount("sub-erin", "erin", { storeId: "shinjuku" });

function judge2(facts: TokenFacts, action: Action, orderId: string): string {
  const order = q2Dir.order(orderId);
  if (order === undefined) return "not_found";
  const result = authorizeWithClientRoles(facts, action, order, {
    attributes: q2Dir.attributesOf(facts.sub),
  });
  return result.allow ? "allow" : `deny:${result.stage}`;
}

const dave = factsFor({ sub: "sub-dave", username: "dave", clientRoles: ["orders-admin"] });
const erin = factsFor({ sub: "sub-erin", username: "erin", clientRoles: ["refund-operator"] });
const ghost = factsFor({ sub: "sub-dave", username: "dave", clientRoles: ["ghost-role"] });

check("orders-admin は担当店舗の登録が無くても全店舗を読める", judge2(dave, "read", "order-9001"), "allow");
check("orders-admin は担当店舗の注文も読める", judge2(dave, "read", "order-1001"), "allow");
check("orders-admin は取り消し済みの注文を返金できる", judge2(dave, "refund", "order-1003"), "allow");
check("orders-admin でも取り消されていない注文は返金できない", judge2(dave, "refund", "order-1001"), "deny:subject");
check("refund-operator は読み取りの権限を増やさない", judge2(erin, "read", "order-1001"), "deny:subject");
check("refund-operator は担当店舗の返金だけできる", judge2(erin, "refund", "order-1003"), "allow");
check("refund-operator も担当外店舗では返金できない", judge2(erin, "refund", "order-9001"), "deny:subject");
check("知らないクライアントロールは無視される", judge2(ghost, "read", "order-1001"), "deny:subject");
check("read に効くのは orders-admin だけ", applicableGrants(["orders-admin", "refund-operator"], "read").length, 1);
check("refund には両方が効く", applicableGrants(["orders-admin", "refund-operator"], "refund").length, 2);

// 問題 3 は文章での分類なので、このスクリプトでは検証しません（解答章の解説を参照）。

// 問題 4: 所有者チェックを sub ベースへ移行する
console.log("\n問題 4: 所有者チェックを sub ベースへ移行する");
const aliceReal = factsFor({ sub: "sub-alice", username: "alice" });
const impostor = factsFor({ sub: "sub-attacker", username: "alice" });

const lenient = new MigratingDirectory("lenient");
check("移行中は利用者名で通ってしまう", judgeMigration(lenient, aliceReal, "read", "order-1001"), "allow");
check("同じ名前の別人でも通ってしまう", judgeMigration(lenient, impostor, "read", "order-1001"), "allow");
check("代用したことが記録に残る", lenient.warnings.length, 2);

const strict = new MigratingDirectory("strict");
check("strict では未連携の注文は誰の持ち物でもない", judgeMigration(strict, aliceReal, "read", "order-1001"), "deny:subject");
check("strict では代用の記録も出ない", strict.warnings.length, 0);

const linked = new MigratingDirectory("lenient");
check("紐づいた注文の件数", linked.linkAccount("sub-alice", "alice"), 4);
check("紐づけ後は sub で通る", judgeMigration(linked, aliceReal, "read", "order-1001"), "allow");
check("紐づけ後は同名の別人を弾く", judgeMigration(linked, impostor, "read", "order-1001"), "deny:subject");
check("紐づけ後は代用の記録が出ない", linked.warnings.length, 0);

// 問題 5: 権限を取り上げてから効くまでの窓
console.log("\n問題 5: 権限を取り上げてから効くまでの窓");
const q5Dir = new BookstoreDirectory();
q5Dir.linkAccount("sub-alice", "alice");
q5Dir.linkAccount("sub-bob", "bob", { storeId: "shinjuku" });
const canceled = q5Dir.order("order-1003");
if (canceled === undefined) throw new Error("order-1003 が台帳に見つかりません");

const bobAttributes = q5Dir.attributesOf("sub-bob");
const oldToken = factsFor({
  sub: "sub-bob",
  username: "bob",
  realmRoles: ["customer", "staff"],
  issuedAt: 1_000,
  expiresAt: 1_300,
});
const newToken = factsFor({
  sub: "sub-bob",
  username: "bob",
  realmRoles: ["customer"],
  issuedAt: 1_200,
  expiresAt: 1_500,
});

const log = new RevocationLog();
check("失効記録が無ければ判定に進む", gate(log, oldToken, "refund", canceled, { attributes: bobAttributes }).status, 200);
check("何もしなければ残る窓（発行 50 秒後）", log.remainingWindow(oldToken, 1_050), 250);
check("失効時刻を過ぎれば窓は 0", log.remainingWindow(oldToken, 1_400), 0);

log.revokeBefore("sub-bob", 1_100);
check("記録より前に発行されたトークンは受け付けない", gate(log, oldToken, "refund", canceled, { attributes: bobAttributes }), {
  status: 401,
  error: "invalid_token",
  stage: "revoked",
});
check("staff を外した後のトークンは判定に進んで落ちる", gate(log, newToken, "refund", canceled, { attributes: bobAttributes }), {
  status: 403,
  error: "forbidden",
  stage: "subject",
});
check("別人のトークンは影響を受けない", log.isRevoked(factsFor({ sub: "sub-alice", issuedAt: 1_000 })), false);
log.revokeBefore("sub-bob", 1_050); // 前に戻そうとしても効かない
check("記録した時刻は前に戻らない", log.isRevoked(factsFor({ sub: "sub-bob", issuedAt: 1_075 })), true);
check("記録している利用者の数", log.size, 1);

// 問題 6: ポリシーを表に寄せる
console.log("\n問題 6: ポリシーを表に寄せる");
const q6Dir = new BookstoreDirectory();
q6Dir.linkAccount("sub-alice", "alice");
q6Dir.linkAccount("sub-bob", "bob", { storeId: "shinjuku" });
q6Dir.linkAccount("sub-carol", "carol", { storeId: "shinjuku" });
q6Dir.linkAccount("sub-dave", "dave", { storeId: "shinjuku", suspended: true });

const subjects = [
  { name: "alice", facts: factsFor({ sub: "sub-alice", username: "alice" }) },
  { name: "bob", facts: factsFor({ sub: "sub-bob", username: "bob", realmRoles: ["customer", "staff"] }) },
  { name: "carol", facts: factsFor({ sub: "sub-carol", username: "carol", clientRoles: ["orders-admin"] }) },
  { name: "dave", facts: factsFor({ sub: "sub-dave", username: "dave", realmRoles: ["customer", "staff"] }) },
  { name: "narrow", facts: factsFor({ sub: "sub-alice", username: "alice", scopes: ["openid"] }) },
];

const cases = buildCases(subjects);
check("ポリシー表の行数", RULES.length, 3);
check("refund を許す条件の組", findRule("refund").anyOf, [["staff", "same-store"]]);
check("総当たりのケース数", cases.length, 75);
check("元の実装と表の実装が食い違ったケース", compare(q6Dir, cases), []);

// 表に寄せても、落ちた段（scope / subject）まで一致していることを 1 件だけ抜き出して見せる
const order1001 = q6Dir.order("order-1001");
if (order1001 === undefined) throw new Error("order-1001 が台帳に見つかりません");
const narrowFacts = factsFor({ sub: "sub-alice", username: "alice", scopes: ["openid"] });
check(
  "スコープ不足は表の実装でも scope の段で落ちる",
  evaluate(narrowFacts, "read", order1001, q6Dir.attributesOf("sub-alice")).stage,
  "scope",
);

console.log(
  failures === 0
    ? "\nセッション 11 練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
