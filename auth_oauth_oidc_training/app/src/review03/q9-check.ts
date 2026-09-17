// 横断復習③ 問題 9 の確認スクリプト。realm には一切触らず、連携ログイン 7 ケースを順に流して
// 結果と副作用（対応表の件数）を確かめます。
// 実行: docker compose exec app npx tsx src/review03/q9-check.ts
import { AccountLinks } from "../mid01/mid01-accounts.js";
import type { ExternalClaims } from "../session15/rp-attribute-mapping.js";
import { FederatedUserStore } from "../session15/rp-jit-provisioning.js";
import type { FederatedKey } from "../session15/rp-jit-provisioning.js";
import { resolveFederatedLogin } from "./q9-federated-login.js";

const PARTNER = "http://keycloak:8080/realms/partner";
const carolKey: FederatedKey = { issuer: PARTNER, subject: "carol-subject" };
const daveKey: FederatedKey = { issuer: PARTNER, subject: "dave-subject" };
const erinKey: FederatedKey = { issuer: PARTNER, subject: "erin-subject" };
const danKey: FederatedKey = { issuer: PARTNER, subject: "dan-subject" };
/** 別の IdP が carol のメールアドレスを名乗ってくる（連携鍵は違う） */
const impostorKey: FederatedKey = { issuer: "https://idp.another-partner.example", subject: "carol-subject" };

/** 相手が storeId を名乗っている点に注目。マッピングの定義は constant の "ueno" です */
const carol = { preferred_username: "carol", email: "carol@partner.example", name: "Carol Partner", groups: ["partner-staff"], storeId: "shinjuku" };
const dave = { preferred_username: "dave", email: "dave@partner.example", name: "Dave Partner", groups: ["partner-staff"] };
const erin = { preferred_username: "erin", email: "erin@partner.example", name: "Erin Partner", groups: ["partner-members", "partner-admins"] };
/** email クレームが無い。必須なのでレコードを作らせません */
const dan = { preferred_username: "dan", name: "Dan Partner", groups: ["partner-members"] };

const store = new FederatedUserStore();
const links = new AccountLinks();
let failed = 0;

const check = (label: string, ok: boolean, detail: string): void => {
  if (!ok) failed += 1;
  console.log(`${ok ? "OK" : "NG"} ${label}: ${detail}`);
};

/** 1 回のログインを流し、結果を 1 行の文字列にして期待値と突き合わせます */
function step(label: string, key: FederatedKey, tokenSub: string, claims: ExternalClaims, expected: string, expectedLinks: number): void {
  const result = resolveFederatedLogin({ store, links, federatedKey: key, tokenSub, claims });
  const actual =
    result.status === 200
      ? `200 ${result.outcome} ${result.ownerId} dropped=${JSON.stringify(result.dropped)}`
      : `${result.status} ${result.error} ${result.detail}`;
  const ok = actual === expected && links.size === expectedLinks;
  check(label, ok, ok ? `${actual} / links=${links.size}` : `${actual} / links=${links.size}（期待 ${expected} / links=${expectedLinks}）`);
}

step("carol の初回ログイン", carolKey, "sub-carol", carol, "200 created shop-1 dropped=[]", 1);
step("carol の 2 回目", carolKey, "sub-carol", carol, "200 reused shop-1 dropped=[]", 1);
step("別の IdP が carol のメールを名乗る", impostorKey, "sub-impostor", carol, "409 account_link_required shop-1", 1);
step("email クレームが無い", danKey, "sub-dan", dan, "422 profile_incomplete email", 1);
step("dave の初回ログイン", daveKey, "sub-dave", dave, "200 created shop-2 dropped=[]", 2);
step("知らないグループ名が混ざる", erinKey, "sub-erin", erin, '200 created shop-3 dropped=["partner-admins"]', 3);
store.deactivate("shop-1"); // 提携先から「carol は退職しました」と連絡が来た
step("退職者の再ログイン", carolKey, "sub-carol", carol, "403 account_deactivated shop-1", 3);

// 相手が名乗った storeId は採用されず、グループは許可リスト経由でロールになっています
const carolUser = store.findByKey(carolKey);
check(
  "相手が名乗った storeId を採らない",
  carolUser?.profile.storeId === "ueno" && JSON.stringify(carolUser?.profile.roles) === '["staff"]',
  `storeId=${carolUser?.profile.storeId ?? "(なし)"} roles=${JSON.stringify(carolUser?.profile.roles)}`,
);

// 拒否したログインの sub は対応表に載っていません
check(
  "拒否したログインは対応表を汚さない",
  links.ownerIdOf("sub-carol") === "shop-1" && links.ownerIdOf("sub-impostor") === undefined && links.ownerIdOf("sub-dan") === undefined,
  `sub-carol=${links.ownerIdOf("sub-carol") ?? "(なし)"} sub-impostor=${links.ownerIdOf("sub-impostor") ?? "(なし)"}`,
);

if (failed > 0) process.exit(1);
console.log("9 項目すべてが期待どおりです");
