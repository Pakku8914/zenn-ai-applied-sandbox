// セッション 15 の自己検証スクリプト。
// realm は 1 つも作りません・1 か所も書き換えません（realm を作って消す実験は
// admin-federation-experiment.ts に隔離してあります）。
// 期待値と一致しない項目が 1 つでもあれば非 0 で終了します。
import { CLIENT_ID } from "../session06/bookstore-client.js";
import { ISSUER } from "../session04/bookstore-endpoints.js";
import { TRUST_MATERIALS, checkTrust, missingTrust } from "./bookstore-sso-actors.js";
import { chooseProtocol, factsOf } from "./bookstore-saml-oidc.js";
import { GROUP_TO_ROLE, PARTNER_MAPPING, applyUpdate, mapClaims } from "./rp-attribute-mapping.js";
import type { ShopProfile } from "./rp-attribute-mapping.js";
import { FederatedUserStore, keyOf } from "./rp-jit-provisioning.js";
import type { FederatedKey, ShopUser } from "./rp-jit-provisioning.js";
import { coverageOf, delayedEvents, reconcile, uncoveredEvents } from "./rp-lifecycle-sync.js";
import type { IdpUser, SyncAction } from "./rp-lifecycle-sync.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) {
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

console.log("=== セッション 15 の検証 ===\n");

// 1. 信頼関係の材料
console.log("1. SSO の構成要素");
check("信頼関係の材料は 4 つ", TRUST_MATERIALS.length, 4);
check(
  "材料の種類",
  TRUST_MATERIALS.map((material) => material.kind),
  ["issuer-id", "signing-key", "endpoints", "client-registration"],
);

// 2. discovery から材料が採れているか（信頼関係の材料は実在するデータで確かめる）
console.log("\n2. bookstore realm の discovery");
const res = await fetch(`${ISSUER}/.well-known/openid-configuration`);
check("discovery の取得", res.status, 200);
const discovery = (await res.json()) as Record<string, unknown>;
check("issuer", discovery["issuer"], ISSUER);
check("userinfo_endpoint の型", typeof discovery["userinfo_endpoint"], "string");
// 連携が増えると「どこまでログアウトするか」が問題になります（セッション 9 の続き）
check("end_session_endpoint の型", typeof discovery["end_session_endpoint"], "string");
check("back-channel logout に対応している", discovery["backchannel_logout_supported"], true);

const trust = checkTrust(discovery, CLIENT_ID);
check("欠けている材料", missingTrust(trust), []);
const partial = checkTrust({ issuer: "http://keycloak:8080/realms/partner" }, undefined);
check("issuer しか分からないとき", missingTrust(partial), ["signing-key", "endpoints", "client-registration"]);
check(
  "クライアント登録は discovery に出てこない",
  checkTrust(discovery, undefined).filter((entry) => !entry.satisfied).length,
  1,
);

// 3. SAML と OIDC の比較・選択
console.log("\n3. SAML と OIDC");
check("SAML のデータ形式", factsOf("saml2").dataFormat, "XML");
check("SAML の署名の単位", factsOf("saml2").signatureScope, "XML 文書の一部（Assertion 単位）");
check("OIDC の署名の単位", factsOf("oidc").signatureScope, "トークン全体（3 部で 1 単位）");

const baseReq = { hasNativeApp: false, needsApiToken: false, partnerPolicy: "none" } as const;
check("相手に窓口が無い", chooseProtocol({ ...baseReq, partnerSupports: [] }).protocol, "none");
check("SAML だけ", chooseProtocol({ ...baseReq, partnerSupports: ["saml2"] }).protocol, "saml2");
check(
  "SAML だけを選ぶ理由",
  chooseProtocol({ ...baseReq, partnerSupports: ["saml2"] }).reason,
  "相手の窓口が SAML だけ。古いからではなく、開いている窓口がそこしかない",
);
check("OIDC だけ", chooseProtocol({ ...baseReq, partnerSupports: ["oidc"] }).protocol, "oidc");
check("両方あるとき", chooseProtocol({ ...baseReq, partnerSupports: ["saml2", "oidc"] }).protocol, "oidc");
check(
  "モバイルアプリがある",
  chooseProtocol({ ...baseReq, partnerSupports: ["saml2", "oidc"], hasNativeApp: true }).protocol,
  "oidc",
);
check(
  "相手の規定が SAML",
  chooseProtocol({ ...baseReq, partnerSupports: ["saml2", "oidc"], partnerPolicy: "saml2" }).protocol,
  "saml2",
);
check(
  "規定は SAML だが窓口は OIDC しかない",
  chooseProtocol({ ...baseReq, partnerSupports: ["oidc"], partnerPolicy: "saml2" }).protocol,
  "oidc",
);

// 4. 属性マッピング
console.log("\n4. 属性マッピング");
const CAROL_CLAIMS = {
  sub: "carol-subject",
  preferred_username: "carol",
  email: "carol@partner.example",
  name: "Carol Partner",
  groups: ["partner-staff", "partner-admins"],
  // 相手が名乗った店舗。こちらは写し取りません
  storeId: "shinjuku",
};

check("許可リストの大きさ", Object.keys(GROUP_TO_ROLE).length, 2);
check("マッピング定義の数", PARTNER_MAPPING.length, 5);

const mapped = mapClaims(CAROL_CLAIMS);
check("写し取りに成功する", mapped.ok, true);
if (!mapped.ok) {
  throw new Error("マッピングが失敗しました（以降の検証が続けられません）");
}
check("username", mapped.profile.username, "carol");
check("email", mapped.profile.email, "carol@partner.example");
check("displayName", mapped.profile.displayName, "Carol Partner");
check("storeId はこちらで決めた値", mapped.profile.storeId, "ueno");
check("ロールは許可リストにある組だけ", mapped.profile.roles, ["staff"]);
check("捨てたグループ名", mapped.dropped, ["partner-admins"]);

const noEmail = mapClaims({ preferred_username: "carol", name: "Carol Partner", groups: [] });
check("email が無いときは失敗", noEmail.ok, false);
check("足りない属性", noEmail.ok ? [] : noEmail.missing, ["email"]);

const unknownGroupsOnly = mapClaims({ ...CAROL_CLAIMS, groups: ["partner-admins", "everyone"] });
check("知らないグループだけなら権限は付かない", unknownGroupsOnly.ok ? unknownGroupsOnly.profile.roles : ["?"], []);
check(
  "groups クレームが無くても失敗しない",
  mapClaims({ preferred_username: "carol", email: "carol@partner.example" }).ok,
  true,
);

const updated = mapClaims({
  ...CAROL_CLAIMS,
  preferred_username: "carol-renamed",
  name: "Carol Ueno",
  groups: ["partner-members"],
});
if (!updated.ok) {
  throw new Error("2 回目のマッピングが失敗しました");
}
const applied = applyUpdate(mapped.profile, updated.profile);
check("上書きされた属性", applied.changed, ["displayName", "roles"]);
check("username は初回の値を守る", applied.profile.username, "carol");
check("displayName は上書きする", applied.profile.displayName, "Carol Ueno");
check("ロールは毎回写し直す", applied.profile.roles, ["customer"]);
check("storeId も初回の値を守る", applied.profile.storeId, "ueno");

// 5. ジャストインタイムプロビジョニング
console.log("\n5. 初回ログインでのレコード作成");
const PARTNER_ISSUER = "http://keycloak:8080/realms/partner";
const SECOND_ISSUER = "https://idp.another-partner.example";
const CAROL_KEY: FederatedKey = { issuer: PARTNER_ISSUER, subject: "carol-subject" };
const SAME_SUBJECT_KEY: FederatedKey = { issuer: SECOND_ISSUER, subject: "carol-subject" };

check("鍵は issuer と subject の組", keyOf(CAROL_KEY) === keyOf(SAME_SUBJECT_KEY), false);

const LOCAL_RECORD: ShopUser = {
  userId: "shop-1",
  key: { issuer: "local", subject: "carol-local" },
  profile: {
    username: "carol-local",
    email: "carol@partner.example",
    displayName: "Carol（手作業で作ったレコード）",
    storeId: "shinjuku",
    roles: ["customer"],
  },
  active: true,
  createdBy: "manual",
};

const store = new FederatedUserStore([LOCAL_RECORD]);
const conflict = store.provision(CAROL_KEY, mapped.profile);
check("同じメールアドレスの既存レコードがあると拒否する", conflict.outcome, "rejected");
check("衝突した相手", conflict.outcome === "rejected" ? conflict.userId : "?", "shop-1");
check("拒否の理由", conflict.outcome === "rejected" ? conflict.reason : "?", "email-conflict");
check("勝手にレコードを増やさない", store.size, 1);

const linked = store.linkExisting(CAROL_KEY, "shop-1");
check("本人確認の後で結び付ける", linked.outcome, "linked");
check("連携鍵で引けるようになる", store.findByKey(CAROL_KEY)?.userId, "shop-1");

const second = store.provision(CAROL_KEY, mapped.profile);
check("2 回目は同じレコードを返す", second.outcome, "reused");
check("レコードは増えない", store.size, 1);

const otherPartner: ShopProfile = { ...mapped.profile, email: "carol@another-partner.example" };
const created = store.provision(SAME_SUBJECT_KEY, otherPartner);
check("別の IdP の同じ subject は別人として作る", created.outcome, "created");
check("採番された ID", created.outcome === "created" ? created.user.userId : "?", "shop-2");
check("レコードは 2 件", store.size, 2);

check("利用を止める", store.deactivate("shop-2"), true);
const afterLeave = store.provision(SAME_SUBJECT_KEY, otherPartner);
check("止めたあとのログインは拒否する", afterLeave.outcome, "rejected");
check("拒否の理由", afterLeave.outcome === "rejected" ? afterLeave.reason : "?", "deactivated");
check("レコードは消さない", store.size, 2);

// 6. ライフサイクルの同期（SCIM が代行している計算）
console.log("\n6. 名簿の差分");
const K_CAROL: FederatedKey = { issuer: PARTNER_ISSUER, subject: "carol-subject" };
const K_DAVE: FederatedKey = { issuer: PARTNER_ISSUER, subject: "dave-subject" };
const K_ERIN: FederatedKey = { issuer: PARTNER_ISSUER, subject: "erin-subject" };
const K_FRANK: FederatedKey = { issuer: PARTNER_ISSUER, subject: "frank-subject" };

const profileOf = (username: string, email: string, displayName: string): ShopProfile => ({
  username,
  email,
  displayName,
  storeId: "ueno",
  roles: ["staff"],
});

const IDP_ROSTER: readonly IdpUser[] = [
  // 表示名が変わった
  { key: K_CAROL, userName: "carol", email: "carol@partner.example", displayName: "Carol Ueno", active: true },
  // 入社したが、まだ書店にログインしていない
  { key: K_DAVE, userName: "dave", email: "dave@partner.example", displayName: "Dave Partner", active: true },
  // 退職した
  { key: K_ERIN, userName: "erin", email: "erin@partner.example", displayName: "Erin Partner", active: false },
];

const SHOP_ROSTER: readonly ShopUser[] = [
  {
    userId: "shop-1",
    key: K_CAROL,
    profile: profileOf("carol", "carol@partner.example", "Carol Partner"),
    active: true,
    createdBy: "jit",
  },
  {
    userId: "shop-2",
    key: K_ERIN,
    profile: profileOf("erin", "erin@partner.example", "Erin Partner"),
    active: true,
    createdBy: "jit",
  },
  {
    // 書店が自分で作ったレコード。連携の同期対象にはしない
    userId: "shop-3",
    key: { issuer: "local", subject: "bob" },
    profile: profileOf("bob", "bob@bookstore.example", "Bob"),
    active: true,
    createdBy: "manual",
  },
  {
    // IdP の名簿から消えた（人事が行を削除した）
    userId: "shop-4",
    key: K_FRANK,
    profile: profileOf("frank", "frank@partner.example", "Frank Partner"),
    active: true,
    createdBy: "jit",
  },
];

const actions = reconcile(IDP_ROSTER, SHOP_ROSTER);
check(
  "差分の種類と順序",
  actions.map((action) => action.kind),
  ["update", "create", "deactivate", "deactivate"],
);

const actionAt = (index: number): SyncAction => {
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
check("ログイン前の入社者も作る", actionAt(1), {
  kind: "create",
  key: K_DAVE,
  userName: "dave",
  email: "dave@partner.example",
});
check("退職者を止める", actionAt(2), { kind: "deactivate", userId: "shop-2" });
check("名簿から消えた人も止める", actionAt(3), { kind: "deactivate", userId: "shop-4" });
check(
  "手作業のレコードは触らない",
  actions.some((action) => action.kind !== "create" && action.userId === "shop-3"),
  false,
);

console.log("\n7. 構成ごとに埋まらない出来事");
check("JIT だけのときに埋まらない出来事", uncoveredEvents("jit-only"), ["leave"]);
check("JIT だけのときに次のログインまで待つ出来事", delayedEvents("jit-only"), [
  "join",
  "attribute-change",
  "group-change",
]);
check("SCIM を足すと埋まらない出来事は無くなる", uncoveredEvents("jit+scim"), []);
check("退職の扱い（JIT だけ）", coverageOf("jit-only", "leave"), "not-covered");
check("退職の扱い（JIT + SCIM）", coverageOf("jit+scim", "leave"), "automatic");

console.log(
  failures === 0 ? "\nセッション 15 のすべての検証に成功しました。" : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
