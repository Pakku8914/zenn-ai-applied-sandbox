// セッション 16 の練習問題の自己検証スクリプト。
// realm は 1 か所も書き換えません（読み取りだけ行います）。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。
import type { AuditEvent } from "./api-service-audit-log.js";
import { JtiDenyList } from "./api-service-revocation-policy.js";
import type { RevocationInput } from "./api-service-revocation-policy.js";
import { BOOKSTORE_LIFESPANS, SAFE_RUNBOOK } from "./bookstore-rotation-plan.js";
import type { ManagedKey, PublishedKey } from "./bookstore-keys.js";
import { STORAGES, chooseStorage, reviewStorage } from "./admin-q1-key-storage.js";
import { buildInventory, fetchInventory, nextAction, observedStage } from "./admin-q2-key-inventory.js";
import { findLeaks, isSafeLine, sanitizeLine } from "./api-q3-log-redaction.js";
import {
  callsPerSecond,
  chooseLevel,
  delaySeconds,
  describe,
  meetsDelay,
} from "./api-q4-revocation-window.js";
import type { PerSensitivity, TrafficMix } from "./api-q4-revocation-window.js";
import { isSafeRunbook, planRunbook, reviewRunbook, runbookLines } from "./admin-q5-rotation-runbook.js";
import { analyze, applyOrders, findingReport, toOrders } from "./api-q6-audit-pipeline.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 16 の練習問題の検証 ===\n");

// 問題 1: 鍵の保管場所
console.log("問題 1: 鍵の保管場所");
check("比較する保管場所は 4 つ", Object.keys(STORAGES).length, 4);
check("HSM だけ鍵が外に出ない", STORAGES["hsm"].keyLeavesBoundary, false);
check("リポジトリに置いたときの指摘", reviewStorage("source-code"), [
  "in-version-control",
  "no-access-log",
  "key-is-exportable",
]);
check("環境変数の指摘", reviewStorage("env-var"), ["no-access-log", "key-is-exportable"]);
check("Secret Manager の指摘", reviewStorage("secret-manager"), ["key-is-exportable"]);
check("HSM の指摘", reviewStorage("hsm"), []);
check(
  "鍵を外に出せない要件",
  chooseStorage({ needsAccessLog: false, mustNotExportKey: true, canUseManagedService: true }).storage,
  "hsm",
);
check(
  "読んだ記録が要る要件",
  chooseStorage({ needsAccessLog: true, mustNotExportKey: false, canUseManagedService: true }).storage,
  "secret-manager",
);
check(
  "記録が要るのに保管サービスが使えない",
  chooseStorage({ needsAccessLog: true, mustNotExportKey: false, canUseManagedService: false }).storage,
  "unsatisfiable",
);
check(
  "どちらも要らないなら環境変数",
  chooseStorage({ needsAccessLog: false, mustNotExportKey: false, canUseManagedService: true }).storage,
  "env-var",
);
check(
  "ソースコード直書きは要件に関わらず選ばれない",
  [
    chooseStorage({ needsAccessLog: false, mustNotExportKey: false, canUseManagedService: false }).storage,
    chooseStorage({ needsAccessLog: true, mustNotExportKey: true, canUseManagedService: false }).storage,
  ].includes("source-code"),
  false,
);

// 問題 2: 鍵の棚卸し
console.log("\n問題 2: 鍵の棚卸し");
check("鍵が 1 本も無い", observedStage([]), "no-key");
check("鍵が 1 本", observedStage(["rsa-1"]), "single");
check("鍵が 2 本", observedStage(["rsa-2", "rsa-1"]), "overlap");

const FAKE_PUBLISHED: readonly PublishedKey[] = [
  { kid: "rsa-1", use: "sig", alg: "RS256" },
  { kid: "enc-1", use: "enc", alg: "RSA-OAEP" },
];
const FAKE_MANAGED: readonly ManagedKey[] = [
  { kid: "rsa-1", use: "SIG", algorithm: "RS256", status: "ACTIVE" },
  { kid: "hmac-1", use: "SIG", algorithm: "HS512", status: "ACTIVE" },
  { kid: "enc-1", use: "ENC", algorithm: "RSA-OAEP", status: "ACTIVE" },
  { kid: "rsa-0", use: "SIG", algorithm: "RS256", status: "PASSIVE" },
];
const fake = buildInventory(FAKE_PUBLISHED, FAKE_MANAGED);
check("公開されている署名鍵", fake.publishedSigningKids, ["rsa-1"]);
check("内部で ACTIVE な署名鍵", fake.internalActiveSigKids, ["rsa-1", "hmac-1"]);
check("JWKS に出ない方式", fake.internalOnlyAlgorithms, ["HS512"]);
check("外から見える段階", fake.stage, "single");
check(
  "1 本しか無いときにできること",
  nextAction("single"),
  "鍵は 1 本。いま消すとすべてのトークンが検証できなくなるので、足すことしかできない",
);

const live = await fetchInventory();
check("いまの認可サーバーの段階", live.stage, "single");
check("いまも対称鍵は JWKS に出ていない", live.internalOnlyAlgorithms, ["HS512"]);

// 問題 3: ログの点検
console.log("\n問題 3: ログの点検");
const SAMPLE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.c2lnbmF0dXJlZGF0YQ";
const BAD_LINE =
  "POST /token 200 authorization=Basic YXBpLXNlcnZpY2U6c2VjcmV0 code_verifier=0123456789abcdef " +
  `access_token=${SAMPLE_JWT}`;
const BAD_URL_LINE = "redirect to http://localhost:3100/callback?state=s1&code=abc.def";
const SAFE_LINE =
  '{"at":"2026-09-08T00:00:00.000Z","event":"authz.denied","sub":"alice-sub","jti":"j-1","decision":"deny"}';

check(
  "トークンログの指摘",
  findLeaks(BAD_LINE).map((leak) => leak.kind),
  ["jwt", "basic-credentials", "forbidden-field", "forbidden-field", "forbidden-field"],
);
check(
  "どのキーで捕まえたか",
  findLeaks(BAD_LINE)
    .filter((leak) => leak.kind === "forbidden-field")
    .map((leak) => leak.hint),
  ["access_token", "authorization", "code_verifier"],
);
check(
  "URL のクエリに認可コードが残っている",
  findLeaks(BAD_URL_LINE).map((leak) => leak.kind),
  ["forbidden-field", "url-secret"],
);
check("組み立て直した記録は安全", isSafeLine(SAFE_LINE), true);
check("伏せた後は安全", isSafeLine(sanitizeLine(BAD_LINE)), true);
check("URL も伏せれば安全", isSafeLine(sanitizeLine(BAD_URL_LINE)), true);
check("伏せた行にトークンは残らない", sanitizeLine(BAD_LINE).includes(SAMPLE_JWT), false);
check("伏せても行の構造は残る", sanitizeLine(BAD_LINE).startsWith("POST /token 200 "), true);
check("ヒントに秘密そのものを入れない", findLeaks(BAD_LINE).some((leak) => leak.hint.includes("eyJ")), false);

// 問題 4: 失効の窓と往復の回数
console.log("\n問題 4: 失効の窓と往復の回数");
const INPUT: RevocationInput = {
  accessTokenLifespan: 300,
  blacklistPropagationSeconds: 10,
  introspectionCacheSeconds: 0,
};
const MIX: TrafficMix = { read: 200, write: 20, admin: 2 };
const LOOSE: PerSensitivity = { read: 600, write: 600, admin: 600 };

check("手元で検証するときの遅れ", delaySeconds("none", "admin", INPUT), 300);
check("聞くときの遅れ", delaySeconds("admin", "admin", INPUT), 0);
check("重い操作だけ聞いても、軽い操作の遅れは変わらない", delaySeconds("admin", "write", INPUT), 300);
check("問い合わせが増えない方針", callsPerSecond("none", MIX), 0);
check("重い操作だけ聞く", callsPerSecond("admin", MIX), 2);
check("書き込みも聞く", callsPerSecond("admin+write", MIX), 22);
check("全部聞く", callsPerSecond("all", MIX), 222);
check("緩い要件なら何もしなくても満たせる", meetsDelay("none", INPUT, { mustRevokeWithinSeconds: LOOSE, callBudgetPerSecond: 50 }), true);

check(
  "緩い要件では問い合わせを増やさない",
  chooseLevel(INPUT, { mustRevokeWithinSeconds: LOOSE, callBudgetPerSecond: 50 }, MIX),
  { level: "none", calls: 0, reason: "遅れの要件を満たし、問い合わせは毎秒 0 回で予算内" },
);
check(
  "管理操作だけ 5 秒以内",
  chooseLevel(
    INPUT,
    { mustRevokeWithinSeconds: { read: 600, write: 600, admin: 5 }, callBudgetPerSecond: 50 },
    MIX,
  ).level,
  "admin",
);
check(
  "書き込みも 30 秒以内",
  chooseLevel(
    INPUT,
    { mustRevokeWithinSeconds: { read: 600, write: 30, admin: 5 }, callBudgetPerSecond: 50 },
    MIX,
  ).level,
  "admin+write",
);
const overBudget = chooseLevel(
  INPUT,
  { mustRevokeWithinSeconds: { read: 60, write: 30, admin: 5 }, callBudgetPerSecond: 50 },
  MIX,
);
check("読み取りまで 60 秒以内にすると予算を超える", overBudget.level, "unsatisfiable");
check("そのとき必要になる問い合わせ", overBudget.calls, 222);
check(
  "キャッシュを置くと、聞いても要件を満たせない",
  chooseLevel(
    { ...INPUT, introspectionCacheSeconds: 60 },
    { mustRevokeWithinSeconds: { read: 600, write: 600, admin: 5 }, callBudgetPerSecond: 500 },
    MIX,
  ).reason,
  "どの方針でも遅れの要件を満たせない。アクセストークンの寿命を短くする",
);
check("管理操作は聞く", describe("admin", "admin"), "認可サーバーに聞く");
check("読み取りは手元で検証する", describe("admin", "read"), "手元で検証");

// 問題 5: 手順書の査読
console.log("\n問題 5: 手順書の査読");
check("本文の手順は指摘なし", reviewRunbook(SAFE_RUNBOOK), []);
check("本文の手順は安全", isSafeRunbook(SAFE_RUNBOOK), true);
check(
  "載せる前に切り替える",
  reviewRunbook([
    "switch-signing",
    "add-key",
    "wait-propagation",
    "wait-retirement",
    "remove-old-key",
  ]).map((problem) => problem.code),
  ["switch-before-add"],
);
check(
  "待ちを省いた手順",
  reviewRunbook(["add-key", "switch-signing", "remove-old-key"]).map((problem) => problem.code),
  ["missing-step", "missing-step", "no-propagation-wait", "no-retirement-wait"],
);
check(
  "切り替える前に消す",
  reviewRunbook([
    "add-key",
    "wait-propagation",
    "remove-old-key",
    "wait-retirement",
    "switch-signing",
  ]).map((problem) => problem.code),
  ["remove-before-switch"],
);
check(
  "待ちなしで消すと何が落ちるか",
  reviewRunbook(["add-key", "wait-propagation", "switch-signing", "remove-old-key"]).map(
    (problem) => problem.impact,
  ),
  [
    "古い kid で署名されたトークンが全部切れるまで待つ が抜けている",
    "古い鍵で署名された、期限内のトークンが検証できなくなる",
  ],
);
check(
  "待ち時間を埋めた手順書",
  planRunbook(BOOKSTORE_LIFESPANS).map((planned) => planned.waitSeconds),
  [0, 35, 0, 1805, 0],
);
check("手順書は 5 行", runbookLines(BOOKSTORE_LIFESPANS).length, 5);
check(
  "待ちの行には秒数が入る",
  runbookLines(BOOKSTORE_LIFESPANS)[1],
  "2. 検証側が新しい kid を知るまで待つ（35 秒待つ）",
);

// 問題 6: 監査ログから気づく
console.log("\n問題 6: 監査ログから気づく");
const ev = (over: Partial<AuditEvent>): AuditEvent => ({
  at: "2026-09-08T00:00:00.000Z",
  event: "authz.denied",
  sub: "alice-sub",
  iss: "http://keycloak:8080/realms/bookstore",
  jti: "j-1",
  clientId: "web-app",
  audience: ["api-service"],
  decision: "deny",
  reason: "staff ロールが必要",
  ip: "192.0.2.10",
  ...over,
});

const EVENTS: readonly AuditEvent[] = [
  ev({}),
  ev({}),
  ev({}),
  ev({ event: "authz.granted", decision: "allow", jti: "j-2", reason: "" }),
  ev({ event: "authz.granted", decision: "allow", sub: "bob-sub", jti: "j-9", ip: "192.0.2.20", reason: "" }),
  ev({ event: "authz.granted", decision: "allow", sub: "bob-sub", jti: "j-9", ip: "192.0.2.21", reason: "" }),
  // 検証に失敗した理由に、トークンをそのまま貼ってしまった記録
  ev({ event: "token.rejected", sub: "", jti: "", reason: `検証に失敗: ${SAMPLE_JWT}` }),
];

const findings = analyze(EVENTS);
check(
  "気づきの種類と順序",
  findings.map((finding) => finding.kind),
  ["repeated-denial", "privilege-jump", "token-shared", "log-leak"],
);
check(
  "誰について気づいたか",
  findings.map((finding) => finding.sub),
  ["alice-sub", "alice-sub", "bob-sub", ""],
);
check(
  "拒否が続いたことの説明",
  findingReport(findings)[0],
  "repeated-denial: 拒否が 3 回続いた",
);
check(
  "しきい値を下げると早く気づく",
  analyze(EVENTS, { denialThreshold: 2 }).filter((finding) => finding.kind === "repeated-denial").length,
  1,
);
check(
  "1 件だけの拒否では気づかない",
  analyze([ev({})]).length,
  0,
);

const orders = toOrders(findings);
check(
  "失効の指示",
  orders.map((order) => `${order.target}:${order.sub}${order.jti === "" ? "" : `/${order.jti}`}`),
  ["session:alice-sub", "token:bob-sub/j-9"],
);
const deny = new JtiDenyList();
check("手元のブロックリストに反映できるのはトークン単位だけ", applyOrders(deny, orders, 2_000), 1);
check("反映されたトークン", deny.isRevoked("j-9"), true);
check("セッションの停止は認可サーバー側の仕事", deny.size, 1);

console.log(
  failures === 0
    ? "\nセッション 16 の練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
