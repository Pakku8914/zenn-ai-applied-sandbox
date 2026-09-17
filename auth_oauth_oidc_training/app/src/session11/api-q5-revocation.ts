// 問題 5 の解答: 「権限を取り上げてから、古いトークンが通らなくなるまで」の窓を塞ぎます。
// トークンに載った権限は発行時点のスナップショットなので、API 側に
// 「この時刻より前に発行されたトークンは受け付けない」という記録を置きます。
import type { Action, Order } from "../session02/api-authz-decide.js";
import type { TokenFacts } from "./api-authz-claims.js";
import { authorize } from "./api-authz-policy.js";
import type { AuthzOptions } from "./api-authz-policy.js";

export class RevocationLog {
  /** sub → この epoch 秒より前に発行されたトークンは無効 */
  private readonly notBefore = new Map<string, number>();

  /** 権限を変えた（取り上げた）ことを記録します。時刻は前に戻しません */
  revokeBefore(sub: string, atSeconds: number): void {
    const current = this.notBefore.get(sub) ?? 0;
    this.notBefore.set(sub, Math.max(current, atSeconds));
  }

  /** このトークンは失効済みか（発行が記録より前なら失効） */
  isRevoked(facts: TokenFacts): boolean {
    return facts.issuedAt < (this.notBefore.get(facts.sub) ?? 0);
  }

  /**
   * 何も手を打たなかった場合に、このトークンが通用し続ける残り秒数。
   * これが「権限を取り上げても効かない待ち時間」の正体です。
   */
  remainingWindow(facts: TokenFacts, nowSeconds: number): number {
    return Math.max(0, facts.expiresAt - nowSeconds);
  }

  get size(): number {
    return this.notBefore.size;
  }
}

export type GateResult = {
  readonly status: 200 | 401 | 403;
  readonly error: string;
  /** どこで決まったか。revoked は失効記録による打ち切り */
  readonly stage: "revoked" | "scope" | "subject" | "granted";
};

/**
 * 失効記録 → スコープ → 利用者の権限、の順に通します。
 * 失効は 401（トークンそのものを受け付けない）で、権限不足は 403 です。
 */
export function gate(
  log: RevocationLog,
  facts: TokenFacts,
  action: Action,
  order: Order,
  options: AuthzOptions = {},
): GateResult {
  if (log.isRevoked(facts)) {
    return { status: 401, error: "invalid_token", stage: "revoked" };
  }
  const result = authorize(facts, action, order, options);
  if (result.allow) {
    return { status: 200, error: "", stage: "granted" };
  }
  return {
    status: 403,
    error: result.stage === "scope" ? "insufficient_scope" : "forbidden",
    stage: result.stage,
  };
}
