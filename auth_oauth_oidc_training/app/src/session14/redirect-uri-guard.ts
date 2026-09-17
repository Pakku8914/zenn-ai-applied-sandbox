// セッション 14: リダイレクト URI を「完全一致」で照合するガード。
// 本書の realm は学習の都合で web-app に http://localhost:3100/* を登録しています（ワイルドカード）。
// OAuth 2.1 が求めるのは完全一致なので、クライアント側でももう一段、
// 登録済みの正確な URI とだけ 1 文字違わず一致させます。
import { isWildcardRegistration, matchesRegistration } from "../session12/mobile-redirect.js";

/** realm に登録されている値（学習用のワイルドカード）。セッション 6 の bookstore-client と同じ前提です */
export const WILDCARD_REGISTRATION = "http://localhost:3100/*";

/** OAuth 2.1 が求める完全一致の許可リスト。web-app が実際に受け取るのは /callback だけです */
export const EXACT_REDIRECT_URIS = ["http://localhost:3100/callback"] as const;

/**
 * 完全一致で判定します。前方一致・ドメイン一致・末尾スラッシュの揺れをすべて弾きます。
 * 「登録済みの正確な文字列に含まれるか」だけを見るので、抜け道が生まれません。
 */
export function isAllowedRedirectUri(
  uri: string,
  allowlist: readonly string[] = EXACT_REDIRECT_URIS,
): boolean {
  return allowlist.includes(uri);
}

export type RedirectCheck = {
  readonly uri: string;
  /** realm のワイルドカード登録なら通ってしまうか（照合が緩い） */
  readonly passesWildcard: boolean;
  /** 完全一致の許可リストなら通るか（本来あるべき厳しさ） */
  readonly passesExactMatch: boolean;
};

/** ワイルドカード登録と完全一致の差を 1 本ずつ並べます */
export function compareMatching(uris: readonly string[]): RedirectCheck[] {
  return uris.map((uri) => ({
    uri,
    passesWildcard: matchesRegistration(WILDCARD_REGISTRATION, uri),
    passesExactMatch: isAllowedRedirectUri(uri),
  }));
}

/** ワイルドカード登録が使われているか（true なら「照合が緩い」前提で運用する必要があります） */
export const registrationIsLoose = (registered: string): boolean => isWildcardRegistration(registered);
