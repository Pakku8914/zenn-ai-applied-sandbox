// 問題2（セッション15 後半）: 届いたクレームを 1 つずつ仕分け、写してはいけないものを落とす。
// 本文の GROUP_TO_ROLE（グループ名の許可リスト）を、クレーム名の段階まで広げたものです。
import { GROUP_TO_ROLE } from "./rp-attribute-mapping.js";
import type { ExternalClaims } from "./rp-attribute-mapping.js";

// 仕分けに使う 4 つのリスト。ALLOWED = そのまま写す / GROUPS = 許可リストを通してから写す /
// SELF_DECIDED = こちらで決めるので採らない / TOKEN_INTERNAL = トークンの仕組みに属する値
export const ALLOWED_CLAIMS: readonly string[] = ["preferred_username", "email", "name"];
export const GROUPS_CLAIM = "groups";
export const SELF_DECIDED_CLAIMS: readonly string[] = ["roles", "realm_access", "resource_access", "storeId", "scope"];
export const TOKEN_INTERNAL_CLAIMS: readonly string[] = ["iss", "sub", "aud", "exp", "iat", "nonce", "azp", "typ"];

/** 扱いの名前が、そのまま「落とした理由」になります */
export type ClaimVerdict = "copy" | "map-through-allowlist" | "drop-self-decided" | "drop-token-internal" | "drop-unknown";

/** 判定の順序に意味があります。「こちらで決める値」を先に見ないと、許可リストの編集ミスが権限に直結します */
export function verdictFor(claim: string): ClaimVerdict {
  if (SELF_DECIDED_CLAIMS.includes(claim)) return "drop-self-decided";
  if (TOKEN_INTERNAL_CLAIMS.includes(claim)) return "drop-token-internal";
  if (claim === GROUPS_CLAIM) return "map-through-allowlist";
  return ALLOWED_CLAIMS.includes(claim) ? "copy" : "drop-unknown";
}

export type ScreenResult = {
  readonly copied: readonly string[];
  readonly mapped: readonly string[];
  /** 落としたクレームと、その扱い。黙って捨てないのが要点です */
  readonly dropped: readonly { readonly claim: string; readonly verdict: ClaimVerdict }[];
  /** groups を許可リストに通した結果のロール */
  readonly roles: readonly string[];
};

/** グループ名を許可リストに通してロールに直します（知らない名前は捨てます） */
export function rolesFromGroups(groups: readonly string[]): readonly string[] {
  const roles: string[] = [];
  for (const group of groups) {
    const role = GROUP_TO_ROLE[group];
    if (role !== undefined && !roles.includes(role)) {
      roles.push(role);
    }
  }
  return roles;
}

/** 並び順は入力の順を保ちます（同じトークンなら毎回同じ報告になります） */
export function screenClaims(claims: ExternalClaims): ScreenResult {
  const copied: string[] = [];
  const mapped: string[] = [];
  const dropped: { claim: string; verdict: ClaimVerdict }[] = [];
  for (const claim of Object.keys(claims)) {
    const verdict = verdictFor(claim);
    if (verdict === "copy") {
      copied.push(claim);
    } else if (verdict === "map-through-allowlist") {
      mapped.push(claim);
    } else {
      dropped.push({ claim, verdict });
    }
  }
  const groups = claims[GROUPS_CLAIM];
  const names = Array.isArray(groups) ? groups.filter((item): item is string => typeof item === "string") : [];
  return { copied, mapped, dropped, roles: rolesFromGroups(names) };
}
