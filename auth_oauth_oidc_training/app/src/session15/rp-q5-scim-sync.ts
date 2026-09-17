// 問題5: 差分同期に「権限の変更」と「復職」を足し、SCIM の要求まで組み立てる。
// 本文の reconcile() は email と displayName しか見ていません。実務で先に問題になるのは権限です。
import { GROUP_TO_ROLE } from "./rp-attribute-mapping.js";
import { keyOf } from "./rp-jit-provisioning.js";
import type { FederatedKey, ShopUser } from "./rp-jit-provisioning.js";

/** SCIM 2.0 のスキーマ識別子（RFC 7643 / RFC 7644） */
export const USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User";
export const PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp";

/**
 * SCIM の要求 1 件の形。
 * 向きに注目してください。要求を出すのは IdP 側で、受けるのは書店側です（ログインの向きとは逆）。
 */
export type ScimRequest = {
  readonly method: "POST" | "PATCH";
  readonly path: string;
  readonly body: Readonly<Record<string, unknown>>;
};

/** IdP 側の名簿。本文の IdpUser にグループを足したもの */
export type IdpMember = {
  readonly key: FederatedKey;
  readonly userName: string;
  readonly email: string;
  readonly displayName: string;
  readonly groups: readonly string[];
  readonly active: boolean;
};

/** 許可リストを通したロール。知らないグループは捨てます（本文と同じ方針） */
export const rolesOf = (groups: readonly string[]): readonly string[] => {
  const roles: string[] = [];
  for (const group of groups) {
    const role = GROUP_TO_ROLE[group];
    if (role !== undefined && !roles.includes(role)) {
      roles.push(role);
    }
  }
  return roles;
};

export type MemberChange =
  | { readonly field: "email" | "displayName"; readonly value: string }
  | { readonly field: "roles"; readonly value: readonly string[] };

export type MemberSyncAction =
  | {
      readonly kind: "create";
      readonly key: FederatedKey;
      readonly userName: string;
      readonly email: string;
      readonly roles: readonly string[];
    }
  | { readonly kind: "update"; readonly userId: string; readonly changes: readonly MemberChange[] }
  | { readonly kind: "deactivate"; readonly userId: string }
  | { readonly kind: "reactivate"; readonly userId: string };

const sameRoles = (left: readonly string[], right: readonly string[]): boolean =>
  JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());

/**
 * 名簿の差分を出します。判定の順序は
 * 「居ない → 作る」「在籍していない → 止める」「止まっているのに在籍 → 戻す」「属性の差 → 直す」です。
 */
export function reconcileMembers(
  members: readonly IdpMember[],
  shopUsers: readonly ShopUser[],
): readonly MemberSyncAction[] {
  const shopByKey = new Map<string, ShopUser>();
  for (const user of shopUsers) {
    shopByKey.set(keyOf(user.key), user);
  }

  const actions: MemberSyncAction[] = [];
  const seen = new Set<string>();

  for (const member of members) {
    const id = keyOf(member.key);
    seen.add(id);
    const shop = shopByKey.get(id);
    const roles = rolesOf(member.groups);

    if (shop === undefined) {
      if (member.active) {
        actions.push({ kind: "create", key: member.key, userName: member.userName, email: member.email, roles });
      }
      continue;
    }
    if (!member.active) {
      if (shop.active) {
        actions.push({ kind: "deactivate", userId: shop.userId });
      }
      continue;
    }
    if (!shop.active) {
      // 復職。権限も一緒に戻すので、この後の update でロールを直します
      actions.push({ kind: "reactivate", userId: shop.userId });
    }

    const changes: MemberChange[] = [];
    if (member.email !== shop.profile.email) {
      changes.push({ field: "email", value: member.email });
    }
    if (member.displayName !== shop.profile.displayName) {
      changes.push({ field: "displayName", value: member.displayName });
    }
    if (!sameRoles(roles, shop.profile.roles)) {
      changes.push({ field: "roles", value: roles });
    }
    if (changes.length > 0) {
      actions.push({ kind: "update", userId: shop.userId, changes });
    }
  }

  for (const shop of shopUsers) {
    if (seen.has(keyOf(shop.key)) || shop.createdBy === "manual") {
      continue;
    }
    if (shop.active) {
      actions.push({ kind: "deactivate", userId: shop.userId });
    }
  }
  return actions;
}

const pathOf = (field: MemberChange["field"]): string =>
  field === "email" ? "emails[primary eq true].value" : field === "displayName" ? "displayName" : "roles";

export function scimRequestForMember(action: MemberSyncAction): ScimRequest {
  switch (action.kind) {
    case "create":
      return {
        method: "POST",
        path: "/scim/v2/Users",
        body: {
          schemas: [USER_SCHEMA],
          externalId: action.key.subject,
          userName: action.userName,
          emails: [{ value: action.email, primary: true }],
          roles: action.roles.map((role) => ({ value: role })),
          active: true,
        },
      };
    case "update":
      return {
        method: "PATCH",
        path: `/scim/v2/Users/${action.userId}`,
        body: {
          schemas: [PATCH_SCHEMA],
          Operations: action.changes.map((change) => ({
            op: "replace",
            path: pathOf(change.field),
            value: change.field === "roles" ? change.value.map((role) => ({ value: role })) : change.value,
          })),
        },
      };
    case "deactivate":
    case "reactivate":
      return {
        method: "PATCH",
        path: `/scim/v2/Users/${action.userId}`,
        body: {
          schemas: [PATCH_SCHEMA],
          Operations: [{ op: "replace", path: "active", value: action.kind === "reactivate" }],
        },
      };
  }
}

/** 何件ずつ動いたかの集計（同期を運用に載せるときは、この数を毎回記録します） */
export function summary(actions: readonly MemberSyncAction[]): Readonly<Record<MemberSyncAction["kind"], number>> {
  return {
    create: actions.filter((action) => action.kind === "create").length,
    update: actions.filter((action) => action.kind === "update").length,
    deactivate: actions.filter((action) => action.kind === "deactivate").length,
    reactivate: actions.filter((action) => action.kind === "reactivate").length,
  };
}
