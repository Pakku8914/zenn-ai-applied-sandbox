// スコープの扱いと、書店の機能に対するスコープ設計。
// スコープは「空白区切りの集合」で、並び順に意味はありません（RFC 6749 §3.3）。

export const parseScope = (scope: string | undefined): string[] =>
  (scope ?? "").split(" ").filter((item) => item.length > 0);

/** 比較やログのために、重複を除いて並べ替えた形に直します */
export const normalizeScope = (scope: string | undefined): string =>
  [...new Set(parseScope(scope))].sort().join(" ");

/** 2 つのスコープ文字列が「集合として」同じかどうか */
export const sameScopeSet = (a: string | undefined, b: string | undefined): boolean =>
  normalizeScope(a) === normalizeScope(b);

export const hasScope = (granted: string | undefined, scope: string): boolean =>
  parseScope(granted).includes(scope);

/** 必要なスコープのうち、付与されていないものを返します（空配列なら足りている） */
export const missingScopes = (granted: string | undefined, required: readonly string[]): string[] =>
  required.filter((scope) => !hasScope(granted, scope));

/**
 * 書店の機能 → その機能を呼ぶために必要なスコープ。
 * ここに書いた orders:* / inventory:* は「設計の成果物」で、realm には登録していません
 * （実際にスコープやロールを作って付与するのはセッション 11 の担当です）。
 */
export const FEATURE_SCOPES: Record<string, readonly string[]> = {
  "本の一覧を見る": [],
  "自分の注文を見る": ["orders:read"],
  "注文する": ["orders:write"],
  "全員の注文を見る": ["orders:read:all"],
  "在庫を書き換える": ["inventory:write"],
};

export function requiredScopesFor(feature: string): readonly string[] {
  const scopes = FEATURE_SCOPES[feature];
  if (scopes === undefined) throw new Error(`知らない機能です: ${feature}`);
  return scopes;
}

/** 使う機能の一覧から、認可リクエストに書くスコープ文字列を組み立てます */
export function scopeRequestFor(
  features: readonly string[],
  base: readonly string[] = ["openid"],
): string {
  return normalizeScope([...base, ...features.flatMap((feature) => requiredScopesFor(feature))].join(" "));
}
