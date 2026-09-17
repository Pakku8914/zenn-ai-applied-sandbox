/**
 * スコープの定義と、認証済みの文脈（誰・何を許されているか）の受け渡し
 *
 * スコープ名は「リソース:動作」の形で揃えます（docs:read / docs:admin）。
 * この命名なら、サーバーが増えても衝突せず、権限一覧を人間が読めます。
 */
import { AsyncLocalStorage } from "node:async_hooks";

/** 読み取り。このサーバーに触るための最低条件 */
export const SCOPE_DOCS_READ = "docs:read";
/** 管理操作。読み取りとは別のスコープに分ける（読み取り専用スコープの分離） */
export const SCOPE_DOCS_ADMIN = "docs:admin";

export const SUPPORTED_SCOPES: readonly string[] = [SCOPE_DOCS_READ, SCOPE_DOCS_ADMIN];

/** ツール名 → 呼び出しに必要なスコープ。表で持つと監査しやすい */
export const TOOL_SCOPES: Readonly<Record<string, string>> = {
  search_documents: SCOPE_DOCS_READ,
  reindex_documents: SCOPE_DOCS_ADMIN,
};

export type AuthContext = {
  readonly subject: string;
  readonly clientId: string | undefined;
  readonly scopes: readonly string[];
  readonly expiresAt: number;
  readonly tokenId: string | undefined;
  /** ログ用の相関 ID。トークン本体ではなく sha256 の先頭 8 文字 */
  readonly fingerprint: string;
};

/**
 * リクエストごとの認証文脈を、引数を引き回さずに下流へ渡す。
 * HTTP 層（ミドルウェア）で set し、MCP 層（ツールのハンドラ）で get します。
 *
 * ★ 生のアクセストークンは文脈に入れません。持ち回さなければ、
 *   うっかり下流 API へ転送する（token passthrough / 11 節）実装が書けません。
 */
const authStore = new AsyncLocalStorage<AuthContext>();

export function runWithAuth<T>(context: AuthContext, fn: () => T): T {
  return authStore.run(context, fn);
}

export function currentAuth(): AuthContext | undefined {
  return authStore.getStore();
}

export function hasScope(scope: string, context = currentAuth()): boolean {
  return context !== undefined && context.scopes.includes(scope);
}

/**
 * ツール単位のスコープ検査。足りなければツール実行層の失敗（isError）を返す。
 * セッション11 の判断表の「権限がない」行に合わせ、3 要素（何が・どう直す・再試行可否）で書きます。
 */
export function denyIfMissingScope(tool: string):
  | { content: { type: "text"; text: string }[]; isError: true }
  | undefined {
  const required = TOOL_SCOPES[tool];
  if (required === undefined || hasScope(required)) {
    return undefined;
  }
  const context = currentAuth();
  const granted =
    context === undefined || context.scopes.length === 0 ? "なし" : context.scopes.join(", ");
  return {
    content: [
      {
        type: "text",
        text: [
          `[forbidden] ツール ${tool} の実行には権限 ${required} が必要です。`,
          `次の一手: いま付与されている権限は ${granted} です。${required} の付与を管理者に依頼してください。` +
            "読み取りだけなら search_documents が使えます。",
          "再試行: 不可（同じトークンで呼び直しても結果は変わりません）",
        ].join("\n"),
      },
    ],
    isError: true,
  };
}
