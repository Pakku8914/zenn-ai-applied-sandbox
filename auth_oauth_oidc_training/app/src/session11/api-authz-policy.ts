// 「クライアントに許された範囲（スコープ）」と「利用者に許された操作（ロール・属性・所有者）」を
// この順に通す判定。利用者側の判断はセッション 2 で書いた decide() をそのまま使います（作り直しません）。
import { decide } from "../session02/api-authz-decide.js";
import type { Action, Order, Subject } from "../session02/api-authz-decide.js";
import { missingScopes } from "../session07/rp-scope.js";
import type { TokenFacts } from "./api-authz-claims.js";

/** 操作 → その操作を呼ぶために必要なスコープ */
export type ScopeRequirements = Record<Action, readonly string[]>;

/** 設計どおりの要件（セッション 7 で命名を決めた orders:read / orders:write） */
export const REQUIRED_SCOPES: ScopeRequirements = {
  read: ["orders:read"],
  cancel: ["orders:write"],
  refund: ["orders:write"],
};

/**
 * スコープをまだ強制しない設定。
 * 今の realm は orders:* を発行しないので、クライアントスコープを登録するまではこちらで動かします
 * （「要求できる状態を作る」→「強制する」の順に進めるのが移行の作法です）。
 */
export const NO_SCOPE_REQUIRED: ScopeRequirements = {
  read: [],
  cancel: [],
  refund: [],
};

/** api-service のクライアントロール → それが与える realm ロール相当の権限 */
export const CLIENT_ROLE_GRANTS: Record<string, readonly string[]> = {
  "orders-admin": ["staff"],
};

export type AuthzResult = {
  readonly allow: boolean;
  /** どの段で決まったか。落ちた段が分かるとログを読むのが楽になります */
  readonly stage: "scope" | "subject" | "granted";
  readonly reason: string;
  /** 足りないスコープ。stage が "scope" のときだけ入ります */
  readonly missing: readonly string[];
};

export type AuthzOptions = {
  /** トークンに載っていない属性（担当店舗・利用停止）。API 側の台帳から渡します */
  readonly attributes?: Subject["attributes"];
  /** 操作ごとのスコープ要件。省略すると厳しい側（設計どおり）になります */
  readonly requiredScopes?: ScopeRequirements;
};

/** トークンの材料を、decide() が受け取る「主体」の形に直します */
export function toSubject(facts: TokenFacts, attributes: Subject["attributes"] = {}): Subject {
  // クライアントロールは realm ロールと別の名前空間にあるので、意味を対応づけてから混ぜます
  const granted = facts.clientRoles.flatMap((role) => CLIENT_ROLE_GRANTS[role] ?? []);
  return {
    userId: facts.sub, // 所有者チェックの軸は sub（preferred_username ではありません）
    roles: [...new Set([...facts.realmRoles, ...granted])].sort(),
    attributes,
  };
}

/**
 * スコープ（クライアントの権限）→ 利用者の権限、の順に判定します。
 * 順序に意味があります。クライアントが要求していない操作は、
 * 利用者がロールを持っていても許してはいけません。
 */
export function authorize(
  facts: TokenFacts,
  action: Action,
  order: Order,
  options: AuthzOptions = {},
): AuthzResult {
  const requirements = options.requiredScopes ?? REQUIRED_SCOPES;
  const missing = missingScopes(facts.scopes.join(" "), requirements[action]);
  if (missing.length > 0) {
    return {
      allow: false,
      stage: "scope",
      reason: `クライアントは ${missing.join(" ")} を要求していません`,
      missing,
    };
  }

  const decision = decide(toSubject(facts, options.attributes ?? {}), action, order);
  return {
    allow: decision.allow,
    stage: decision.allow ? "granted" : "subject",
    reason: decision.reason,
    missing: [],
  };
}
