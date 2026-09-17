// 問題 6 の解答: if の連なりだったポリシーを、1 つのデータ（表）に寄せます。
// 表に寄せると「誰が何を許されるか」をコードを読まずに確認でき、
// 変更が 1 か所で済みます。判定エンジンは表を読むだけの短い関数になります。
import type { Action, Order, Subject } from "../session02/api-authz-decide.js";
import { missingScopes } from "../session07/rp-scope.js";
import type { TokenFacts } from "./api-authz-claims.js";
import type { BookstoreDirectory } from "./api-authz-directory.js";
import { authorize, toSubject } from "./api-authz-policy.js";
import type { AuthzResult } from "./api-authz-policy.js";

/** 満たすべき条件の名前。組み合わせて 1 つの許可条件になります */
export type Requirement = "owner" | "staff" | "same-store";

export type Rule = {
  readonly action: Action;
  readonly requiredScopes: readonly string[];
  /** いずれかの組を満たせば許可。組の中の条件はすべて満たす必要があります */
  readonly anyOf: ReadonlyArray<readonly Requirement[]>;
  /** この状態の注文には、誰であっても許さない */
  readonly denyStatuses: readonly Order["status"][];
  /** この状態のときだけ許す。空なら状態を問わない */
  readonly onlyStatuses: readonly Order["status"][];
};

export const RULES: readonly Rule[] = [
  {
    action: "read",
    requiredScopes: ["orders:read"],
    anyOf: [["owner"], ["staff", "same-store"]],
    denyStatuses: [],
    onlyStatuses: [],
  },
  {
    action: "cancel",
    requiredScopes: ["orders:write"],
    anyOf: [["owner"], ["staff", "same-store"]],
    denyStatuses: ["shipped", "canceled"],
    onlyStatuses: [],
  },
  {
    action: "refund",
    requiredScopes: ["orders:write"],
    anyOf: [["staff", "same-store"]],
    denyStatuses: [],
    onlyStatuses: ["canceled"],
  },
];

export function findRule(action: Action): Rule {
  const rule = RULES.find((item) => item.action === action);
  if (rule === undefined) throw new Error(`ポリシー表に ${action} がありません`);
  return rule;
}

const deny = (stage: "scope" | "subject", reason: string, missing: readonly string[] = []): AuthzResult => ({
  allow: false,
  stage,
  reason,
  missing,
});

/** 1 つの条件を満たしているかを判定します */
function meets(requirement: Requirement, subject: Subject, order: Order): boolean {
  if (requirement === "owner") return subject.userId === order.ownerId;
  if (requirement === "staff") return subject.roles.includes("staff");
  return subject.attributes.storeId === order.storeId;
}

/**
 * 表を読むだけの判定エンジン。
 * 判定の順序（スコープ → 利用停止 → 資源の状態 → 条件の組）は本文の authorize() に合わせます。
 */
export function evaluate(
  facts: TokenFacts,
  action: Action,
  order: Order,
  attributes: Subject["attributes"] = {},
): AuthzResult {
  const rule = findRule(action);
  const subject = toSubject(facts, attributes); // クライアントロールの翻訳はここで済む

  const missing = missingScopes(facts.scopes.join(" "), rule.requiredScopes);
  if (missing.length > 0) {
    return deny("scope", `クライアントは ${missing.join(" ")} を要求していません`, missing);
  }
  if (subject.attributes.suspended === true) {
    return deny("subject", "利用停止中の利用者です");
  }
  if (rule.denyStatuses.includes(order.status)) {
    return deny("subject", `${order.status} の注文に ${action} は許されません`);
  }
  if (rule.onlyStatuses.length > 0 && !rule.onlyStatuses.includes(order.status)) {
    return deny("subject", `${action} は ${rule.onlyStatuses.join("/")} の注文にだけ許されます`);
  }
  if (rule.anyOf.some((set) => set.every((item) => meets(item, subject, order)))) {
    return { allow: true, stage: "granted", reason: "ポリシー表の条件を満たしました", missing: [] };
  }
  return deny("subject", "条件を満たす組がありません");
}

export type RegressionCase = {
  readonly label: string;
  readonly facts: TokenFacts;
  readonly action: Action;
  readonly orderId: string;
};

const ORDER_IDS = ["order-1001", "order-1002", "order-1003", "order-2001", "order-9001"] as const;
const ACTIONS = ["read", "cancel", "refund"] as const;

/** 主体 × 操作 × 注文の総当たり。表に移しても結果が変わらないことを確かめるための材料です */
export function buildCases(subjects: ReadonlyArray<{ name: string; facts: TokenFacts }>): readonly RegressionCase[] {
  const cases: RegressionCase[] = [];
  for (const subject of subjects) {
    for (const action of ACTIONS) {
      for (const orderId of ORDER_IDS) {
        cases.push({ label: `${subject.name}/${action}/${orderId}`, facts: subject.facts, action, orderId });
      }
    }
  }
  return cases;
}

/** 元の実装と表の実装を突き合わせ、食い違ったケースの説明だけを返します（空なら一致） */
export function compare(
  directory: BookstoreDirectory,
  cases: readonly RegressionCase[],
): readonly string[] {
  const mismatches: string[] = [];
  for (const item of cases) {
    const order = directory.order(item.orderId);
    if (order === undefined) throw new Error(`知らない注文です: ${item.orderId}`);
    const attributes = directory.attributesOf(item.facts.sub);
    const before = authorize(item.facts, item.action, order, { attributes });
    const after = evaluate(item.facts, item.action, order, attributes);
    if (before.allow !== after.allow || before.stage !== after.stage) {
      mismatches.push(
        `${item.label}: 元=${before.allow}/${before.stage} 表=${after.allow}/${after.stage}`,
      );
    }
  }
  return mismatches;
}
