// 機能に必要なスコープはセッション7 の FEATURE_SCOPES が持っています（requiredScopesFor で引きます）。
// この章で足すのは、利用者側の要件（ロールと持ち主の一致）と、3 段で判定する checkAccess() です。
import { missingScopes, requiredScopesFor } from "../session07/rp-scope.js";

export type Feature = "本の一覧を見る" | "自分の注文を見る" | "注文する" | "全員の注文を見る" | "在庫を書き換える";

/** 機能ごとの、利用者側の要件。roles は利用者に、ownerOnly は資源に対する条件 */
export type Requirement = {
  readonly roles: readonly string[];
  readonly ownerOnly: boolean;
};

export const REQUIREMENTS: Record<Feature, Requirement> = {
  本の一覧を見る: { roles: [], ownerOnly: false },
  自分の注文を見る: { roles: [], ownerOnly: true },
  注文する: { roles: [], ownerOnly: true },
  全員の注文を見る: { roles: ["staff"], ownerOnly: false },
  在庫を書き換える: { roles: ["staff"], ownerOnly: false },
};

/** 検証済みトークンから取り出した判断材料（セッション11 の TokenFacts から 3 項目だけを取ったもの） */
export type Facts = {
  readonly sub: string;
  readonly scopes: readonly string[];
  readonly realmRoles: readonly string[];
};

/** 対象の資源。存在しなければ undefined を渡します */
export type Target = { readonly ownerSub: string } | undefined;

export type Verdict =
  | { readonly allow: true; readonly status: 200 }
  | {
      readonly allow: false;
      readonly status: 403 | 404;
      readonly error: "insufficient_scope" | "forbidden" | "not_found";
      readonly missing: readonly string[];
      readonly challenge: string | undefined;
      readonly reason: string;
    };

/** 出し直しても結果が変わらない拒否。だから WWW-Authenticate は付けない */
function deny(status: 403 | 404, error: "forbidden" | "not_found", reason: string): Verdict {
  return { allow: false, status, error, missing: [], challenge: undefined, reason };
}

/** スコープ（クライアント）→ ロール（利用者）→ 資源 の順に通します */
export function checkAccess(feature: Feature, facts: Facts, target: Target): Verdict {
  const { roles, ownerOnly } = REQUIREMENTS[feature];

  // 第 1 段: クライアントに許された範囲。足りないものを challenge で伝える
  const missing = missingScopes(facts.scopes.join(" "), requiredScopesFor(feature));
  if (missing.length > 0) {
    return {
      allow: false,
      status: 403,
      error: "insufficient_scope",
      missing,
      challenge: `Bearer realm="api-service", error="insufficient_scope", scope="${missing.join(" ")}"`,
      reason: `クライアントは ${missing.join(" ")} を要求していません`,
    };
  }

  // 第 2 段: 利用者に許された操作
  const lacking = roles.filter((role) => !facts.realmRoles.includes(role));
  if (lacking.length > 0) return deny(403, "forbidden", `この操作には ${lacking.join(" ")} ロールが必要です`);

  // 第 3 段: 資源。存在の有無は、権限を確かめたあとにだけ明かす
  if (ownerOnly) {
    if (target === undefined) return deny(404, "not_found", "対象の注文がありません");
    if (target.ownerSub !== facts.sub) return deny(403, "forbidden", "自分の注文ではありません");
  }
  return { allow: true, status: 200 };
}
