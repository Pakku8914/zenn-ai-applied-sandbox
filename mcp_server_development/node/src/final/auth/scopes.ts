/**
 * スコープの定義と認証文脈の受け渡し
 *
 * セッション12 の scopes.ts は import しません。スコープ名（requests:*）も
 * 語彙（tenantId / tokenRef）も違うので、同じ設計で作り直します。
 * セッション12 の文脈からの詰め替えは serve-core.ts の 1 か所だけで行います。
 */
import { AsyncLocalStorage } from "node:async_hooks";

import type { ToolFailure } from "../observability/errors.js";

export const SCOPE_READ = "requests:read";
export const SCOPE_WRITE = "requests:write";
export const SCOPE_APPROVE = "requests:approve";

export const SUPPORTED_SCOPES: readonly string[] = [SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE];

export const TOOL_NAMES = [
  "search_requests",
  "get_request",
  "save_request",
  "submit_request",
  "decide_request",
  "comment_on_request",
] as const;
export type ToolName = (typeof TOOL_NAMES)[number];

/** ツール名 → 必要なスコープ。表で持つと監査しやすい */
export const TOOL_SCOPES: Readonly<Record<ToolName, string>> = {
  search_requests: SCOPE_READ,
  get_request: SCOPE_READ,
  save_request: SCOPE_WRITE,
  submit_request: SCOPE_WRITE,
  decide_request: SCOPE_APPROVE,
  comment_on_request: SCOPE_WRITE,
};

/** スコープ不足のときに案内する代替手段。「次の一手」を具体的にするため */
const ALTERNATIVES: Readonly<Record<ToolName, string>> = {
  search_requests: "読み取り権限がないため、このサーバーではできることがありません。",
  get_request: "読み取り権限がないため、このサーバーではできることがありません。",
  save_request: "内容の確認だけなら get_request が使えます。",
  submit_request: "提出は申請者本人の操作です。ユーザーに Web 画面からの提出を依頼してください。",
  decide_request: "決裁はできませんが、get_request で内容を確認し comment_on_request で意見を残せます。",
  comment_on_request: "閲覧だけなら get_request が使えます。",
};

export type AuthContext = {
  readonly subject: string;
  readonly clientId: string | undefined;
  readonly scopes: readonly string[];
  readonly expiresAt: number;
  /** トークン本体ではなく相関 ID（sha256 の先頭 8 文字） */
  readonly tokenRef: string;
  readonly tenantId: string;
};

const store = new AsyncLocalStorage<AuthContext>();

export function runWithAuth<T>(context: AuthContext, fn: () => T): T {
  return store.run(context, fn);
}

export function currentAuth(): AuthContext | undefined {
  return store.getStore();
}

export function hasScope(scope: string, context = currentAuth()): boolean {
  return context !== undefined && context.scopes.includes(scope);
}

/**
 * ツール単位のスコープ検査。
 * 足りなければ ToolFailure を返し、呼び出し側が isError のツール結果に変換します。
 * 認証文脈が無い場合も「拒否」です（fail closed）。
 */
export function missingScopeFailure(
  tool: ToolName,
  context: AuthContext | undefined,
): ToolFailure | undefined {
  const required = TOOL_SCOPES[tool];
  if (context !== undefined && context.scopes.includes(required)) return undefined;
  const granted =
    context === undefined || context.scopes.length === 0 ? "なし" : context.scopes.join(", ");
  return {
    code: "forbidden",
    what: `ツール ${tool} の実行には権限 ${required} が必要です（いま付与されている権限: ${granted}）。`,
    next: `${required} の付与を管理者に依頼してください。${ALTERNATIVES[tool]}`,
    retryable: false,
  };
}
