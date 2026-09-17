// 本章の結果を通しで見るデモ。realm には一切触らないので、何度でも実行できます。
// 実行: docker compose exec app npx tsx src/session15/rp-federation-demo.ts
import { applyUpdate, mapClaims } from "./rp-attribute-mapping.js";
import { FederatedUserStore } from "./rp-jit-provisioning.js";
import type { FederatedKey, ProvisionResult } from "./rp-jit-provisioning.js";
import { reconcile, uncoveredEvents } from "./rp-lifecycle-sync.js";

const PARTNER_ISSUER = "http://keycloak:8080/realms/partner";
const SECOND_ISSUER = "https://idp.another-partner.example";
const carolKey: FederatedKey = { issuer: PARTNER_ISSUER, subject: "carol-subject" };

/** 提携先の IdP が渡してきたクレーム（storeId を名乗っているところに注目） */
const carolClaims = {
  preferred_username: "carol",
  email: "carol@partner.example",
  name: "Carol Partner",
  groups: ["partner-staff", "partner-admins"],
  storeId: "shinjuku",
};

const mapped = mapClaims(carolClaims);
console.log(`1. 写し取り: ${JSON.stringify(mapped)}`);
if (!mapped.ok) {
  throw new Error("必須の属性が足りません");
}

const store = new FederatedUserStore();
const outcomeOf = (result: ProvisionResult): string =>
  result.outcome === "rejected" ? `${result.outcome} / ${result.reason}` : `${result.outcome} / ${result.user.userId}`;

console.log(`2. 初回ログイン: ${outcomeOf(store.provision(carolKey, mapped.profile))}`);
console.log(`3. 2 回目のログイン: ${outcomeOf(store.provision(carolKey, mapped.profile))}`);
console.log(
  `4. 別の IdP から同じメールアドレスで: ${outcomeOf(
    store.provision({ issuer: SECOND_ISSUER, subject: "carol-subject" }, mapped.profile),
  )}`,
);

const renamed = mapClaims({ ...carolClaims, name: "Carol Ueno", groups: ["partner-members"] });
if (!renamed.ok) {
  throw new Error("2 回目の写し取りに失敗しました");
}
console.log(`5. 上書きした属性: ${JSON.stringify(applyUpdate(mapped.profile, renamed.profile).changed)}`);

const carolUser = store.findByKey(carolKey);
const actions = reconcile(
  // 人事の名簿では carol が退職済みになった
  [{ key: carolKey, userName: "carol", email: "carol@partner.example", displayName: "Carol Ueno", active: false }],
  carolUser === undefined ? [] : [carolUser],
);
console.log(`6. 退職を反映する差分: ${JSON.stringify(actions)}`);
console.log(`7. JIT だけでは埋まらない出来事: ${JSON.stringify(uncoveredEvents("jit-only"))}`);
