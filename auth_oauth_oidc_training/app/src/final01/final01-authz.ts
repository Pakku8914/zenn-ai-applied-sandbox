// 最終プロジェクト final01: 「誰に何を許すか」の判断を集めたファイル。
// 判断が 2 か所に散ると、一覧と 1 件で結果が食い違います。だからここだけに置きます。
import type { Action, Order, Subject } from "../session02/api-authz-decide.js";
import { AccountLinks } from "../mid01/mid01-accounts.js";
import { ORDERS } from "../mid01/mid01-orders.js";
import type { OrderDetail } from "../mid01/mid01-orders.js";
import { UNLINKED } from "../session11/api-authz-directory.js";
import { NO_SCOPE_REQUIRED, authorize, toSubject } from "../session11/api-authz-policy.js";
import type { AuthzResult } from "../session11/api-authz-policy.js";
import type { TokenFacts } from "../session11/api-authz-claims.js";

/**
 * sub と書店の利用者の対応表に、逆引き（利用者名 → sub）を足したもの。
 * 判断は sub で行うのに、本書の注文台帳は持ち主を利用者名で記録しているためです。
 */
export class BookstoreAccounts extends AccountLinks {
  private readonly subByOwner = new Map<string, string>();

  override link(sub: string, username: string): string {
    const owner = super.link(sub, username);
    // 最初に結び付いた sub を優先する（あとから来た別人に持ち主を移さない）
    if (!this.subByOwner.has(owner)) {
      this.subByOwner.set(owner, sub);
    }
    return owner;
  }

  /** その持ち主の sub。まだ 1 度もログインしていなければ undefined */
  subOf(ownerId: string): string | undefined {
    return this.subByOwner.get(ownerId);
  }
}

/**
 * 台帳の注文を、判断に渡す形（持ち主が sub）に直します。
 * ログインしたことがない利用者の注文は UNLINKED になり、どの sub とも一致しません。
 */
export function asResource(order: OrderDetail, accounts: BookstoreAccounts): Order {
  return {
    orderId: order.orderId,
    ownerId: accounts.subOf(order.ownerId) ?? UNLINKED,
    storeId: order.storeId,
    status: order.status,
  };
}

/**
 * 注文に対する判断。realm は orders:* を発行しないのでスコープの段は通す設定で呼び、
 * 結果を決めるのは decide() の中のロール（staff）と所有者（sub）の 2 段です。
 */
export function decideOrder(
  facts: TokenFacts,
  action: Action,
  order: Order,
  attributes: Subject["attributes"],
): AuthzResult {
  return authorize(facts, action, order, { attributes, requiredScopes: NO_SCOPE_REQUIRED });
}

/** 1 件ずつの判断を並べたものが一覧になる。だから一覧と 1 件で食い違いません */
export function visibleOrders(
  facts: TokenFacts,
  accounts: BookstoreAccounts,
  attributes: Subject["attributes"],
): OrderDetail[] {
  return ORDERS.filter((order) => decideOrder(facts, "read", asResource(order, accounts), attributes).allow);
}

/** 在庫は staff だけ、しかも担当店舗の分だけ。所有者の概念が無い資源です */
export function decideInventory(facts: TokenFacts, attributes: Subject["attributes"]): AuthzResult {
  const subject: Subject = toSubject(facts, attributes);
  if (!subject.roles.includes("staff")) {
    return { allow: false, stage: "subject", reason: "在庫の参照には staff ロールが必要です", missing: [] };
  }
  if (subject.attributes.storeId === undefined) {
    return { allow: false, stage: "subject", reason: "担当店舗が決まっていません", missing: [] };
  }
  return {
    allow: true,
    stage: "granted",
    reason: `担当店舗（${subject.attributes.storeId}）の在庫です`,
    missing: [],
  };
}

/** 集計を許すクライアント。利用者ではなくクライアントで判断する唯一の経路です */
export const REPORT_CLIENTS: readonly string[] = ["batch-worker"];

/**
 * 集計に対する判断。本書の realm はサービスアカウントにロールを割り当てていないので
 * ロールでは判定できず、Client Credentials のトークンには所有者もいません。
 * 許可リストにある azp かどうかだけを見ます。
 */
export function decideReport(azp: string): AuthzResult {
  if (!REPORT_CLIENTS.includes(azp)) {
    return {
      allow: false,
      stage: "subject",
      reason: `${azp === "" ? "(不明)" : azp} に集計は許していません`,
      missing: [],
    };
  }
  return { allow: true, stage: "granted", reason: `${azp} は集計を許されたクライアントです`, missing: [] };
}

/** 判断の結果を、監査ログに書く「出来事」に対応づけます（セッション 16 の AuditEvent の形） */
export function outcomeOf(result: AuthzResult): {
  event: "authz.granted" | "authz.denied";
  decision: "allow" | "deny";
  reason: string;
} {
  return {
    event: result.allow ? "authz.granted" : "authz.denied",
    decision: result.allow ? "allow" : "deny",
    reason: result.reason,
  };
}
