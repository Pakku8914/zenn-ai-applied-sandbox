// 練習問題 5: 書店の機能に対するスコープ設計の点検レポート。
import {
  FEATURE_SCOPES,
  missingScopes,
  normalizeScope,
  requiredScopesFor,
  sameScopeSet,
  scopeRequestFor,
} from "./rp-scope.js";
import { loginHeadless } from "../test-helpers/headless-login.js";

/** 画面（web-app）が使う機能。ここに並べた機能から要求スコープを決めます */
const WEB_APP_FEATURES = ["本の一覧を見る", "自分の注文を見る", "注文する"];

/** 読み取りだけを許すスコープ名かどうか */
const isReadOnly = (scope: string): boolean => scope.includes("read");
/** 1 つのスコープに読み取りと書き込みが同居していないか（同居すると必要以上の権限を渡すことになる） */
const mixesReadAndWrite = (scope: string): boolean => scope.includes("read") && scope.includes("write");

export async function buildScopeDesignReport(): Promise<string[]> {
  const lines = ["=== スコープ設計の点検 ==="];

  for (const feature of Object.keys(FEATURE_SCOPES)) {
    const scopes = requiredScopesFor(feature);
    lines.push(`${feature}: ${scopes.length === 0 ? "（スコープ不要）" : scopes.join(" ")}`);
  }

  lines.push(`画面が要求するスコープ: ${scopeRequestFor(WEB_APP_FEATURES)}`);
  lines.push(
    `orders:read だけで「注文する」を呼ぶと足りないもの: ${missingScopes(
      "openid orders:read",
      requiredScopesFor("注文する"),
    ).join(" ")}`,
  );

  const allScopes = [...new Set(Object.values(FEATURE_SCOPES).flat())];
  lines.push(`機能の数: ${Object.keys(FEATURE_SCOPES).length} / スコープの数: ${allScopes.length}`);
  lines.push(`1 機能 1 スコープになっていない: ${allScopes.length < Object.keys(FEATURE_SCOPES).length}`);
  lines.push(`読み取りと書き込みが混ざったスコープ: ${allScopes.filter(mixesReadAndWrite).length} 件`);
  lines.push(`書き込みを許すスコープ: ${allScopes.filter((scope) => !isReadOnly(scope)).join(" ")}`);

  // realm に実在するスコープで、要求した文字列と付与された文字列を比べる
  const requested = "openid profile email";
  const { tokens } = await loginHeadless({ scope: requested });
  lines.push(`要求した文字列: ${requested}`);
  lines.push(`付与された文字列: ${tokens.scope ?? "(なし)"}`);
  lines.push(`並び順は違うが集合としては同じ: ${sameScopeSet(requested, tokens.scope)}`);
  lines.push(`正規化するとどちらも: ${normalizeScope(tokens.scope)}`);
  lines.push(
    `設計した orders:* は realm にまだ無い（付与されていない）: ${
      missingScopes(tokens.scope, ["orders:read", "orders:write"]).length === 2
    }`,
  );
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q5-scope-design"))) {
  for (const line of await buildScopeDesignReport()) console.log(line);
}
