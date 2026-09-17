// 最終プロジェクト final01: ログインを始める前に「方針どおりか」を確かめる関門。
// PKCE を必須にする・S256 以外を使わない・リダイレクト URI を完全一致で選ぶ——
// どれも 1 か所で検査できます。経路ごとに気をつけるのではなく、出口に関門を置くのが要点です。
import { isAllowedRedirectUri } from "../session14/redirect-uri-guard.js";

/** OAuth 2.1 が要求する方式。plain は受け付けません（セッション 6） */
export const ALLOWED_CODE_CHALLENGE_METHOD = "S256";

/** 方針に反した理由。文面ではなくこの値で分岐します */
export type PolicyViolation =
  | "missing_code_challenge"
  | "weak_code_challenge_method"
  | "missing_state"
  | "missing_nonce"
  | "redirect_uri_not_allowed";

/**
 * 認可エンドポイントへ向ける URL が方針を満たしているかを見ます。
 * 満たしていれば undefined、破っていれば最初に見つかった違反を返します。
 * 「方針を満たしたときだけ利用者を転送する」ために、転送の直前に呼びます。
 */
export function checkAuthorizationUrl(url: URL): PolicyViolation | undefined {
  const params = url.searchParams;
  // PKCE：割符のハッシュが無い認可リクエストは、横取りされた認可コードを交換されうる
  if ((params.get("code_challenge") ?? "") === "") {
    return "missing_code_challenge";
  }
  // S256 のみ。plain は「ハッシュ化しない」＝ URL に割符そのものを出すのと同じ
  if (params.get("code_challenge_method") !== ALLOWED_CODE_CHALLENGE_METHOD) {
    return "weak_code_challenge_method";
  }
  // state：戻ってきたときに「自分が始めたログインか」を見分ける値
  if ((params.get("state") ?? "") === "") {
    return "missing_state";
  }
  // nonce：受け取った ID トークンが「今回の応答か」を見分ける値
  if ((params.get("nonce") ?? "") === "") {
    return "missing_nonce";
  }
  // リダイレクト URI：realm はワイルドカード登録なので、クライアント側で完全一致に絞る（セッション 14）
  if (!isAllowedRedirectUri(params.get("redirect_uri") ?? "")) {
    return "redirect_uri_not_allowed";
  }
  return undefined;
}

/** 割符（code_verifier）が URL に漏れていないか。1 度も URL に出してはいけません */
export function leaksCodeVerifier(url: URL): boolean {
  return url.searchParams.has("code_verifier");
}
