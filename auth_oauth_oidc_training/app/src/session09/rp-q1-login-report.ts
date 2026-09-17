// 問題 1 の解答。/login の応答を「ブラウザに渡したもの」と「サーバー側に控えたもの」に分けて見せます。
import { attribute, hasFlag, parseSetCookie } from "../session03/web-app-cookie-tools.js";
import { SESSION_COOKIE } from "./rp-session-store.js";
import type { RpSessionStore } from "./rp-session-store.js";

export type LoginReport = {
  status: number;
  /** ブラウザに渡した URL に載っているパラメータ（名前だけ。値はログに出さない） */
  browserParams: string[];
  cookie: { name: string; valueLength: number; httpOnly: boolean; sameSite: string; path: string };
  /** サーバー側に控えた 3 点セット（値そのものはログに出さない） */
  kept: string[];
  /** ブラウザに渡した state と、サーバー側に控えた state が一致しているか */
  stateMatches: boolean;
};

export function reportLogin(res: Response, store: RpSessionStore): LoginReport {
  const location = new URL(res.headers.get("location") ?? "");
  const cookie = parseSetCookie(res.headers.get("set-cookie"));
  const session = store.get(cookie?.value);
  const attempt = session?.attempt;
  return {
    status: res.status,
    browserParams: [...location.searchParams.keys()].sort(),
    cookie: {
      name: cookie?.name ?? "(なし)",
      valueLength: cookie?.value.length ?? 0,
      httpOnly: cookie !== undefined && hasFlag(cookie, "HttpOnly"),
      sameSite: cookie === undefined ? "(なし)" : attribute(cookie, "SameSite"),
      path: cookie === undefined ? "(なし)" : attribute(cookie, "Path"),
    },
    kept: attempt === undefined ? [] : ["code_verifier", "nonce", "state"],
    stateMatches: attempt !== undefined && attempt.state === location.searchParams.get("state"),
  };
}

/** Cookie ヘッダの形（name=value）。ブラウザが次のリクエストで送る値 */
export function toCookieHeader(res: Response): string {
  return `${SESSION_COOKIE}=${parseSetCookie(res.headers.get("set-cookie"))?.value ?? ""}`;
}
