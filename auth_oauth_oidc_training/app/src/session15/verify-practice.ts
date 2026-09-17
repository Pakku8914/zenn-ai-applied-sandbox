// セッション 15 の練習問題の検証スクリプト。
// realm は 1 つも作りません・1 か所も書き換えません。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。
import { CLIENT_ID } from "../session06/bookstore-client.js";
import { ISSUER } from "../session04/bookstore-endpoints.js";
import { PARTNER_MAPPING } from "./rp-attribute-mapping.js";
import type { ShopProfile } from "./rp-attribute-mapping.js";
import { FederatedUserStore } from "./rp-jit-provisioning.js";
import type { FederatedKey, ShopUser } from "./rp-jit-provisioning.js";
import { blockers, trustReport, trustRows } from "./rp-q1-trust-report.js";
import { comparisonTable, decisionLog, decisionTable } from "./rp-q2-protocol-table.js";
import { RISKY_MAPPING, SAFE_MAPPING, isSafe, reviewRules, reviewTable } from "./rp-q3-mapping-review.js";
import { AccountLinkFlow, sequentialCodes } from "./rp-q4-account-link.js";
import {
  PATCH_SCHEMA,
  USER_SCHEMA,
  reconcileMembers,
  rolesOf,
  scimRequestForMember,
  summary,
} from "./rp-q5-scim-sync.js";
import type { IdpMember, MemberSyncAction } from "./rp-q5-scim-sync.js";
import { PARTNER_INPUTS, planAll, planTable } from "./rp-q6-federation-plan.js";
import { earliestStage, failureFindings, failureTable, latestStage } from "./rp-q7-trust-failure-stage.js";
import { logoutReport, logoutSupport, misreadRisks, supportedStyles, supportsLogout } from "./rp-q8-logout-capability.js";
import { SAMPLE_INPUT, buildBrokerConfig, brokerRedirectUri, reviewInput } from "./rp-q9-broker-config.js";
import { ONBOARDING_INPUTS, onboardingTable, planAllOnboarding } from "./rp-q10-onboarding-plan.js";
import { screenClaims, verdictFor } from "./rp-q11-claim-guard.js";
import { compareAll } from "./rp-q12-email-key-pitfall.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 15 の練習問題の検証 ===\n");

// 前半 問題1: 信頼関係の材料の表
console.log("前半 問題1: 信頼関係の材料");
const discovery = (await (await fetch(`${ISSUER}/.well-known/openid-configuration`)).json()) as Record<
  string,
  unknown
>;
check("bookstore realm では材料がそろう", blockers(discovery, CLIENT_ID), []);
check("すべての行が満たされている", trustRows(discovery, CLIENT_ID).every((row) => row.satisfied), true);
const onlyIssuer = blockers({ issuer: "http://keycloak:8080/realms/partner" }, undefined);
check("issuer しか分からないときの障害", onlyIssuer.length, 3);
check("1 件目は公開鍵", onlyIssuer[0]?.includes("jwks_uri"), true);
const report = trustReport(discovery, CLIENT_ID);
check("表は 6 行（見出し + 区切り + 4 材料）", report.split("\n").length, 6);
check("見出しの列", report.split("\n")[0], "| 材料 | そろっているか | OIDC での採りどころ | SAML での採りどころ |");

// 前半 問題2: 比較表と方式の選択
console.log("\n前半 問題2: SAML と OIDC の比較");
const table = comparisonTable();
check("比較表は 7 行（見出し + 区切り + 5 軸）", table.split("\n").length, 7);
check("1 行目の軸", table.split("\n")[2]?.startsWith("| 伝送方式 |"), true);
check(
  "3 社の判定",
  decisionLog().map((decision) => decision.protocol),
  ["saml2", "oidc", "none"],
);
check(
  "大手チェーンを SAML にする理由",
  decisionLog()[0]?.reason,
  "相手の運用規定で方式が決まっている。こちらの好みより相手の規定が先",
);
check("判定の表は 5 行", decisionTable().split("\n").length, 5);

// 前半 問題3: 材料が欠けたときに失敗する段階
console.log("\n前半 問題3: 材料が欠けたときに失敗する段階");
check("そろっていれば指摘は無い", failureFindings(discovery, CLIENT_ID), []);
check("そろっていれば段階も無い", earliestStage(failureFindings(discovery, CLIENT_ID)), "none");
const partialFindings = failureFindings({ issuer: "http://keycloak:8080/realms/partner" }, undefined);
check(
  "早い順に並ぶ",
  partialFindings.map((finding) => finding.stage),
  ["authorize", "callback", "verify"],
);
check("最初につまずく段階", earliestStage(partialFindings), "authorize");
check("最後まで気づけない段階", latestStage(partialFindings), "verify");
const withoutJwks: Record<string, unknown> = { ...discovery };
delete withoutJwks["jwks_uri"];
check(
  "公開鍵だけが欠けると検証まで気づけない",
  failureFindings(withoutJwks, CLIENT_ID).map((finding) => finding.stage),
  ["verify"],
);
check("表は 5 行（見出し + 区切り + 3 材料）", failureTable({ issuer: "x" }, undefined).split("\n").length, 5);

// 前半 問題4: 出口（ログアウト）の対応状況
console.log("\n前半 問題4: 出口（ログアウト）の対応状況");
check("bookstore realm で使える方式", supportedStyles(discovery), ["rp-initiated", "front-channel", "back-channel"]);
check("バックチャネルログアウトの判定", supportsLogout(discovery, "back-channel"), true);
check(
  "CIBA の申告だけではバックチャネルログアウトと判定しない",
  supportsLogout({ backchannel_token_delivery_modes_supported: ["poll", "ping"] }, "back-channel"),
  false,
);
check("取り違えやすい申告の件数", misreadRisks(discovery).length, 2);
check(
  "セッション単位で閉じられるか",
  logoutSupport(discovery).map((row) => row.sessionAware),
  [false, true, true],
);
check("報告は 5 行（見出し + 区切り + 3 方式）", logoutReport(discovery).split("\n").length, 5);

// 前半 問題5: ブローカー設定の組み立て
console.log("\n前半 問題5: ブローカー設定の組み立て");
const brokerBuilt = buildBrokerConfig(SAMPLE_INPUT);
check("材料がそろえば組み立てられる", brokerBuilt.ok, true);
check(
  "ブローカーの受け口",
  brokerBuilt.ok ? brokerBuilt.value.redirectUri : "?",
  "http://keycloak:8080/realms/bookstore/broker/partner/endpoint",
);
check("相手のメールは信じない", brokerBuilt.ok ? brokerBuilt.value.trustEmail : true, false);
check("要求するスコープ", brokerBuilt.ok ? brokerBuilt.value.config.defaultScope : "?", "openid profile email");
const noClientRegistration = buildBrokerConfig({ ...SAMPLE_INPUT, clientId: undefined });
check("クライアント未発行なら組み立てない", noClientRegistration.ok, false);
check("欠けている材料", noClientRegistration.ok ? [] : noClientRegistration.missing, ["client-registration"]);
check(
  "危ない入力への指摘",
  reviewInput({
    ...SAMPLE_INPUT,
    alias: "Partner IdP",
    clientSecretRef: "bookstore-broker-secret",
    scopes: ["profile"],
  }).length,
  4,
);
check(
  "受け口は別名から決まる",
  brokerRedirectUri("http://keycloak:8080", "bookstore", "major-chain"),
  "http://keycloak:8080/realms/bookstore/broker/major-chain/endpoint",
);

// 前半 問題6: 4 社の受け入れ準備
console.log("\n前半 問題6: 4 社の受け入れ準備");
const onboardings = planAllOnboarding();
check("提携先の数", ONBOARDING_INPUTS.length, 4);
check(
  "4 社の方式",
  onboardings.map((plan) => plan.protocol),
  ["saml2", "oidc", "oidc", "none"],
);
check(
  "つまずく段階",
  onboardings.map((plan) => plan.blockedAt),
  ["none", "none", "callback", "setup"],
);
check(
  "ブローカー設定を今日書けるか",
  onboardings.map((plan) => plan.broker),
  ["not-applicable", "ready", "blocked", "not-applicable"],
);
check(
  "開通できるか",
  onboardings.map((plan) => plan.openable),
  [true, true, false, false],
);
check("小規模書店の出口", onboardings[1]?.exit, ["rp-initiated", "front-channel", "back-channel"]);
check(
  "次の作業の件数",
  onboardings.map((plan) => plan.todos.length),
  [2, 0, 1, 1],
);
check("大手チェーンの申し送り", onboardings[0]?.todos[1], "API のアクセストークンは自分の realm で発行する（SAML では出ない）");
check("準備の表は 6 行", onboardingTable().split("\n").length, 6);

// 後半 問題1: 属性マッピングの査読
console.log("\n後半 問題1: 属性マッピングの査読");
check(
  "危ない定義の指摘",
  reviewRules(RISKY_MAPPING).map((finding) => finding.code),
  [
    "username-from-email",
    "identifier-not-required",
    "self-decided-from-claim",
    "self-decided-from-claim",
    "roles-never-revoked",
  ],
);
check("直した定義には指摘が無い", isSafe(SAFE_MAPPING), true);
check("本文の定義にも指摘が無い", isSafe(PARTNER_MAPPING), true);
check("指摘が無いときの表", reviewTable(SAFE_MAPPING).split("\n").length, 3);

// 後半 問題2: クレームの仕分け
console.log("\n後半 問題2: クレームの仕分け");
const arrivingClaims = {
  preferred_username: "carol",
  email: "carol@partner.example",
  name: "Carol Partner",
  groups: ["partner-staff", "partner-admins"],
  roles: ["admin"],
  storeId: "shinjuku",
  sub: "carol-subject",
  department: "books",
};
const screened = screenClaims(arrivingClaims);
check("そのまま写すクレーム", screened.copied, ["preferred_username", "email", "name"]);
check("許可リストを通すクレーム", screened.mapped, ["groups"]);
check(
  "落としたクレームと理由",
  screened.dropped.map((row) => [row.claim, row.verdict]),
  [
    ["roles", "drop-self-decided"],
    ["storeId", "drop-self-decided"],
    ["sub", "drop-token-internal"],
    ["department", "drop-unknown"],
  ],
);
check("相手が admin を名乗ってもロールは許可リスト経由", screened.roles, ["staff"]);
check("realm_access も採らない", verdictFor("realm_access"), "drop-self-decided");
check("知らないクレームは既定で落とす", verdictFor("department"), "drop-unknown");

// 後半 問題3: 連携鍵をメールアドレスにすると壊れること
console.log("\n後半 問題3: 連携鍵をメールアドレスにすると壊れること");
const comparisons = compareAll();
check("場面の数", comparisons.length, 3);
check(
  "メールアドレスで引いた結果",
  comparisons.map((row) => row.byEmail),
  ["created / shop-2", "reused / shop-1", "reused / shop-1"],
);
check(
  "issuer + subject で引いた結果",
  comparisons.map((row) => row.bySubject),
  ["reused / shop-1", "rejected / email-conflict", "rejected / email-conflict"],
);
check("3 つの場面すべてでメールアドレス方式は事故になる", comparisons.every((row) => row.brokenByEmail), true);
check(
  "場面の並び",
  comparisons.map((row) => row.scenario),
  ["rename", "handover", "cross-idp"],
);

// 後半 問題4: 本人確認を経てからアカウントを結び付ける
console.log("\n後半 問題4: アカウントリンク");
const PARTNER_ISSUER = "http://keycloak:8080/realms/partner";
const CAROL_KEY: FederatedKey = { issuer: PARTNER_ISSUER, subject: "carol-subject" };
const carolProfile: ShopProfile = {
  username: "carol",
  email: "carol@partner.example",
  displayName: "Carol Partner",
  storeId: "ueno",
  roles: ["staff"],
};
const LOCAL_RECORD: ShopUser = {
  userId: "shop-1",
  key: { issuer: "local", subject: "carol-local" },
  profile: { ...carolProfile, username: "carol-local", displayName: "Carol（手作業のレコード）" },
  active: true,
  createdBy: "manual",
};

const store = new FederatedUserStore([LOCAL_RECORD]);
const rejected = store.provision(CAROL_KEY, carolProfile);
check("まず email-conflict で止まる", rejected.outcome === "rejected" ? rejected.reason : "?", "email-conflict");

const flow = new AccountLinkFlow(store, sequentialCodes(["123456"]));
const challenge = flow.begin(CAROL_KEY, "shop-1", 1000);
check("申し込みの ID", challenge.challengeId, "link-1");
check("有効期限", challenge.expiresAt, 1600);
check("保留中の件数", flow.pending, 1);
check("知らない申し込み", flow.confirm("link-9", "123456", 1000), { ok: false, failure: "not-found" });
check("コードが違う", flow.confirm("link-1", "000000", 1000), { ok: false, failure: "wrong-code" });
check("間違えても申し込みは残る", flow.pending, 1);
check("期限切れ", flow.confirm("link-1", "123456", 1700), { ok: false, failure: "expired" });
const confirmed = flow.confirm("link-1", "123456", 1500);
check("正しいコードで結び付く", confirmed.ok, true);
check("結び付いた相手", confirmed.ok ? confirmed.user.userId : "?", "shop-1");
check("使い終わった申し込みは残らない", flow.pending, 0);
check("同じコードは 2 回使えない", flow.confirm("link-1", "123456", 1500), { ok: false, failure: "used" });
check("連携鍵で引けるようになった", store.findByKey(CAROL_KEY)?.userId, "shop-1");
check("レコードは増えていない", store.size, 1);

check("利用を止める", store.deactivate("shop-1"), true);
const flowAfterLeave = new AccountLinkFlow(store, sequentialCodes(["222222"]));
flowAfterLeave.begin(CAROL_KEY, "shop-1", 2000);
check("止めたレコードには結び付けない", flowAfterLeave.confirm("link-1", "222222", 2000), {
  ok: false,
  failure: "deactivated",
});

// 後半 問題5: 権限の変更と復職を含む差分同期
console.log("\n後半 問題5: 差分同期の拡張");
const K_CAROL: FederatedKey = { issuer: PARTNER_ISSUER, subject: "carol-subject" };
const K_DAVE: FederatedKey = { issuer: PARTNER_ISSUER, subject: "dave-subject" };
const K_ERIN: FederatedKey = { issuer: PARTNER_ISSUER, subject: "erin-subject" };
const K_FRANK: FederatedKey = { issuer: PARTNER_ISSUER, subject: "frank-subject" };

check("許可リストを通したロール", rolesOf(["partner-staff", "partner-admins"]), ["staff"]);
check("知らないグループだけなら空", rolesOf(["partner-admins"]), []);

const MEMBERS: readonly IdpMember[] = [
  {
    key: K_CAROL,
    userName: "carol",
    email: "carol@partner.example",
    displayName: "Carol Ueno",
    groups: ["partner-staff"],
    active: true,
  },
  {
    key: K_DAVE,
    userName: "dave",
    email: "dave@partner.example",
    displayName: "Dave Partner",
    groups: ["partner-members"],
    active: true,
  },
  {
    key: K_ERIN,
    userName: "erin",
    email: "erin@partner.example",
    displayName: "Erin Partner",
    groups: ["partner-staff"],
    active: false,
  },
  {
    key: K_FRANK,
    userName: "frank",
    email: "frank@partner.example",
    displayName: "Frank Partner",
    groups: ["partner-members"],
    active: true,
  },
];

const profileOf = (username: string, displayName: string, roles: readonly string[]): ShopProfile => ({
  username,
  email: `${username}@partner.example`,
  displayName,
  storeId: "ueno",
  roles,
});

const SHOP_USERS: readonly ShopUser[] = [
  { userId: "shop-1", key: K_CAROL, profile: profileOf("carol", "Carol Partner", ["staff"]), active: true, createdBy: "jit" },
  { userId: "shop-2", key: K_ERIN, profile: profileOf("erin", "Erin Partner", ["staff"]), active: true, createdBy: "jit" },
  { userId: "shop-3", key: K_FRANK, profile: profileOf("frank", "Frank Partner", ["staff"]), active: false, createdBy: "jit" },
  {
    userId: "shop-4",
    key: { issuer: "local", subject: "bob" },
    profile: profileOf("bob", "Bob", ["staff"]),
    active: true,
    createdBy: "manual",
  },
];

const actions = reconcileMembers(MEMBERS, SHOP_USERS);
check(
  "差分の種類と順序",
  actions.map((action) => action.kind),
  ["update", "create", "deactivate", "reactivate", "update"],
);
check("集計", summary(actions), { create: 1, update: 2, deactivate: 1, reactivate: 1 });

const actionAt = (index: number): MemberSyncAction => {
  const action = actions[index];
  if (action === undefined) {
    throw new Error(`差分 ${index} 件目がありません`);
  }
  return action;
};

check("表示名の更新", actionAt(0), {
  kind: "update",
  userId: "shop-1",
  changes: [{ field: "displayName", value: "Carol Ueno" }],
});
check("復職", actionAt(3), { kind: "reactivate", userId: "shop-3" });
check("権限の付け替え", actionAt(4), {
  kind: "update",
  userId: "shop-3",
  changes: [{ field: "roles", value: ["customer"] }],
});
check("入社の SCIM 要求", scimRequestForMember(actionAt(1)), {
  method: "POST",
  path: "/scim/v2/Users",
  body: {
    schemas: [USER_SCHEMA],
    externalId: "dave-subject",
    userName: "dave",
    emails: [{ value: "dave@partner.example", primary: true }],
    roles: [{ value: "customer" }],
    active: true,
  },
});
check("復職の SCIM 要求", scimRequestForMember(actionAt(3)), {
  method: "PATCH",
  path: "/scim/v2/Users/shop-3",
  body: { schemas: [PATCH_SCHEMA], Operations: [{ op: "replace", path: "active", value: true }] },
});
check("権限の SCIM 要求", scimRequestForMember(actionAt(4)), {
  method: "PATCH",
  path: "/scim/v2/Users/shop-3",
  body: { schemas: [PATCH_SCHEMA], Operations: [{ op: "replace", path: "roles", value: [{ value: "customer" }] }] },
});

// 後半 問題6: 提携先 3 社の受け入れ計画
console.log("\n後半 問題6: 受け入れ計画");
const plans = planAll();
check("提携先の数", PARTNER_INPUTS.length, 3);
check(
  "方式",
  plans.map((plan) => plan.protocol),
  ["saml2", "oidc", "none"],
);
check(
  "プロビジョニング",
  plans.map((plan) => plan.provisioning),
  ["jit+scim", "jit-only", "jit-only"],
);
check(
  "結び付けの方針",
  plans.map((plan) => plan.linking),
  ["auto-by-key", "manual-review", "auto-by-key"],
);
check(
  "ログアウトの方針",
  plans.map((plan) => plan.logout),
  ["saml-slo", "oidc-backchannel", "none"],
);
check(
  "残るリスクの件数",
  plans.map((plan) => plan.risks.length),
  [1, 3, 4],
);
check("大手チェーンのリスク", plans[0]?.risks[0]?.includes("API のアクセストークンが出ない"), true);
check("小規模書店は棚卸しが要る", plans[1]?.risks[0], "leave が自動で反映されない（12 席分の棚卸しを定期作業にする）");
check("計画の表は 5 行", planTable().split("\n").length, 5);

console.log(
  failures === 0
    ? "\nセッション 15 の練習問題のすべての検証に成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
