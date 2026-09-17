// 認証の連携（SSO）とアカウントのライフサイクル管理（プロビジョニング）は別の問題です。
// ここでは SCIM が代行している計算 ―「IdP 側の名簿」と「書店側の名簿」の差分 ― を自分で書きます。
// SCIM の要求そのものを組み立てるのは練習問題 5 の担当です。
import type { FederatedKey, ShopUser } from "./rp-jit-provisioning.js";
import { keyOf } from "./rp-jit-provisioning.js";

/** IdP（人事側）が持っている名簿の 1 行 */
export type IdpUser = {
  readonly key: FederatedKey;
  readonly userName: string;
  readonly email: string;
  readonly displayName: string;
  /** 在籍しているか。退職すると false になる */
  readonly active: boolean;
};

export type FieldChange = {
  readonly field: "email" | "displayName";
  readonly value: string;
};

export type SyncAction =
  | { readonly kind: "create"; readonly key: FederatedKey; readonly userName: string; readonly email: string }
  | { readonly kind: "update"; readonly userId: string; readonly changes: readonly FieldChange[] }
  | { readonly kind: "deactivate"; readonly userId: string };

/**
 * 2 つの名簿を突き合わせて、書店側に必要な操作を並べます。
 * 順序は「IdP の名簿順 → IdP に現れなかった書店側のレコード」に固定します
 * （毎回同じ順序で出ないと、差分を目で追えません）。
 */
export function reconcile(idpUsers: readonly IdpUser[], shopUsers: readonly ShopUser[]): readonly SyncAction[] {
  const shopByKey = new Map<string, ShopUser>();
  for (const user of shopUsers) {
    shopByKey.set(keyOf(user.key), user);
  }

  const actions: SyncAction[] = [];
  const seen = new Set<string>();

  for (const person of idpUsers) {
    const id = keyOf(person.key);
    seen.add(id);
    const shop = shopByKey.get(id);

    if (shop === undefined) {
      // 書店側にまだ居ない。在籍している人だけ作ります
      if (person.active) {
        actions.push({ kind: "create", key: person.key, userName: person.userName, email: person.email });
      }
      continue;
    }
    if (!person.active) {
      // 退職。ログインできなくなるだけでは足りないので、こちらのレコードも止めます
      if (shop.active) {
        actions.push({ kind: "deactivate", userId: shop.userId });
      }
      continue;
    }
    const changes: FieldChange[] = [];
    if (person.email !== shop.profile.email) {
      changes.push({ field: "email", value: person.email });
    }
    if (person.displayName !== shop.profile.displayName) {
      changes.push({ field: "displayName", value: person.displayName });
    }
    if (changes.length > 0) {
      actions.push({ kind: "update", userId: shop.userId, changes });
    }
  }

  for (const shop of shopUsers) {
    if (seen.has(keyOf(shop.key))) {
      continue;
    }
    // 手で作ったレコードは同期の対象にしません（連携とは別の理由で存在しています）
    if (shop.createdBy === "manual") {
      continue;
    }
    if (shop.active) {
      actions.push({ kind: "deactivate", userId: shop.userId });
    }
  }
  return actions;
}

/** アカウントの一生で起きる 4 つの出来事 */
export type LifecycleEvent = "join" | "attribute-change" | "group-change" | "leave";
/** 構成の選択肢 */
export type ProvisionMode = "jit-only" | "jit+scim";
/** その出来事が反映されるまでの「確かさ」 */
export type Coverage = "automatic" | "next-login" | "not-covered";

export const LIFECYCLE_COVERAGE: readonly {
  readonly mode: ProvisionMode;
  readonly event: LifecycleEvent;
  readonly coverage: Coverage;
}[] = [
  { mode: "jit-only", event: "join", coverage: "next-login" },
  { mode: "jit-only", event: "attribute-change", coverage: "next-login" },
  { mode: "jit-only", event: "group-change", coverage: "next-login" },
  { mode: "jit-only", event: "leave", coverage: "not-covered" },
  { mode: "jit+scim", event: "join", coverage: "automatic" },
  { mode: "jit+scim", event: "attribute-change", coverage: "automatic" },
  { mode: "jit+scim", event: "group-change", coverage: "automatic" },
  { mode: "jit+scim", event: "leave", coverage: "automatic" },
];

export function coverageOf(mode: ProvisionMode, event: LifecycleEvent): Coverage {
  const row = LIFECYCLE_COVERAGE.find((entry) => entry.mode === mode && entry.event === event);
  if (row === undefined) {
    throw new Error(`表に無い組み合わせです: ${mode} / ${event}`);
  }
  return row.coverage;
}

/** その構成で埋まらない出来事。ここが残っていると「退職者のアカウントが消えない」問題になります */
export const uncoveredEvents = (mode: ProvisionMode): readonly LifecycleEvent[] =>
  LIFECYCLE_COVERAGE.filter((row) => row.mode === mode && row.coverage === "not-covered").map((row) => row.event);

/** その構成では「本人が次にログインするまで」待たされる出来事 */
export const delayedEvents = (mode: ProvisionMode): readonly LifecycleEvent[] =>
  LIFECYCLE_COVERAGE.filter((row) => row.mode === mode && row.coverage === "next-login").map((row) => row.event);
