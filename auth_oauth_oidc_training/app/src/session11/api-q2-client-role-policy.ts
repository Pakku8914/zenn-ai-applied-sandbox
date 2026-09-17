// 問題 2 の解答: クライアントロールを「意味」に翻訳してから、既存の判定に渡します。
// realm には触りません。クライアントロールが載ったトークンは手で組み立てて試します。
import type { Action, Order, Subject } from "../session02/api-authz-decide.js";
import type { TokenFacts } from "./api-authz-claims.js";
import { authorize } from "./api-authz-policy.js";
import type { AuthzOptions, AuthzResult } from "./api-authz-policy.js";

/** クライアントロール 1 つが与えるもの */
export type ClientRoleGrant = {
  /** 与える realm ロール相当の権限 */
  readonly roles: readonly string[];
  /** 全店舗を担当しているものとして扱うか */
  readonly allStores: boolean;
  /** この操作のときだけ効く。空なら全操作に効く */
  readonly actions: readonly Action[];
};

/**
 * api-service のクライアントロールの定義。
 * 「ロールの名前」と「その名前が意味すること」を 1 か所に集めておくのが要点です。
 */
export const CLIENT_ROLE_DEFINITIONS: Record<string, ClientRoleGrant> = {
  // 全店舗の注文を扱える運用担当
  "orders-admin": { roles: ["staff"], allStores: true, actions: [] },
  // 返金だけを担当する。読み取りや取り消しの権限は増えない
  "refund-operator": { roles: ["staff"], allStores: false, actions: ["refund"] },
};

/** この操作に効くクライアントロールだけを集めます（知らない名前は無視します） */
export function applicableGrants(
  clientRoles: readonly string[],
  action: Action,
): readonly ClientRoleGrant[] {
  return clientRoles
    .map((role) => CLIENT_ROLE_DEFINITIONS[role])
    .filter((grant): grant is ClientRoleGrant => grant !== undefined)
    .filter((grant) => grant.actions.length === 0 || grant.actions.includes(action));
}

/**
 * クライアントロールを realm ロールと属性に翻訳し、そのうえで本文の authorize() を呼びます。
 * 判定のロジックを増やさず、入力を整えるだけで済ませるのが狙いです。
 */
export function authorizeWithClientRoles(
  facts: TokenFacts,
  action: Action,
  order: Order,
  options: AuthzOptions = {},
): AuthzResult {
  const grants = applicableGrants(facts.clientRoles, action);
  const base: Subject["attributes"] = options.attributes ?? {};

  const translated: TokenFacts = {
    ...facts,
    realmRoles: [...new Set([...facts.realmRoles, ...grants.flatMap((grant) => grant.roles)])].sort(),
    // 翻訳済みなので空にする（authorize() の中で二重に効かせない）
    clientRoles: [],
  };

  // 「全店舗担当」は、注文の店舗に自分を合わせることで表現できます
  const attributes: Subject["attributes"] = grants.some((grant) => grant.allStores)
    ? { ...base, storeId: order.storeId }
    : base;

  return authorize(translated, action, order, { ...options, attributes });
}
