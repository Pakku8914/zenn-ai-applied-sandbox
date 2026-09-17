// 「ログインできたか」をどのトークンで判断するか。Bad と Good を並べてあります。
import { createRemoteJWKSet, jwtVerify } from "jose";
import { API_AUDIENCE, ISSUER, JWKS_URI, TOKEN_ENDPOINT } from "./bookstore-oidc.js";
import { IdTokenError, verifyIdToken } from "./rp-verify-id-token.js";
import type { Identity } from "./rp-verify-id-token.js";

const jwks = createRemoteJWKSet(new URL(JWKS_URI));

export type LoginState =
  | { readonly loggedIn: false; readonly reason: string }
  | { readonly loggedIn: true; readonly user: Identity };

/**
 * Bad（セキュリティの問題）: アクセストークンの検証が通ったことを「ログインできた」と読み替えている。
 * セッション 5 で見た破綻そのもので、利用者が一度もログインしていなくても真になります。
 */
export async function badLoginCheck(accessToken: string): Promise<{ loggedIn: boolean; user: string }> {
  try {
    const { payload } = await jwtVerify(accessToken, jwks, {
      algorithms: ["RS256"],
      issuer: ISSUER,
      audience: API_AUDIENCE, // 宛先はリソースサーバー。RP 自身ではない
      clockTolerance: 5,
    });
    const username = payload["preferred_username"];
    return { loggedIn: true, user: typeof username === "string" ? username : "" };
  } catch {
    return { loggedIn: false, user: "" };
  }
}

/**
 * Good（セキュリティの改善）: ID トークンを検証して初めて「ログインできた」と判断する。
 * ID トークンが無い ＝ 認証イベントが無い ＝ 誰もログインしていない、です。
 */
export async function goodLoginCheck(args: {
  idToken: string | undefined;
  expectedNonce: string;
}): Promise<LoginState> {
  if (args.idToken === undefined || args.idToken === "") {
    return { loggedIn: false, reason: "ID トークンが無い（認証イベントが存在しない）" };
  }
  try {
    const user = await verifyIdToken({ idToken: args.idToken, expectedNonce: args.expectedNonce });
    return { loggedIn: true, user };
  } catch (err) {
    if (err instanceof IdTokenError) {
      return { loggedIn: false, reason: err.reason };
    }
    throw err;
  }
}

/** 比較用に、利用者が不在の「機械のトークン」を取ります（セッション 4 と同じ Client Credentials） */
export async function fetchMachineTokens(): Promise<Record<string, unknown>> {
  const res = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: "batch-worker",
      // 学習用サンドボックスの固定値。本番では環境変数や Secret Manager から読みます
      client_secret: "batch-worker-secret",
    }),
  });
  if (!res.ok) {
    throw new Error(`機械のトークンの取得に失敗しました: HTTP ${res.status}`);
  }
  return (await res.json()) as Record<string, unknown>;
}
