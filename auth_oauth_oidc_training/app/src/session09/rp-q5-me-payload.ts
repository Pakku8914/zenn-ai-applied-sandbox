// 問題 5 の解答。/me が返す JSON を 2 通り作り、どちらがブラウザにトークンを出すかを比べます。
import type { RpSession } from "./rp-session-store.js";
import { Hono } from "hono";
import type { MiddlewareHandler } from "hono";

export type MeMode = "leaky" | "safe";

export function buildMePayload(session: RpSession, mode: MeMode, now: number = Date.now()): Record<string, unknown> {
  if (mode === "leaky") {
    // よくある「持っているものをまとめて返す」実装。セッションの中身がそのままブラウザに届く
    return { user: session.user, tokens: session.tokens };
  }
  // 画面に必要なものだけを返す。トークンはサーバー側に置いたまま
  return {
    user: session.user,
    accessTokenExpiresIn: Math.max(0, Math.round(((session.tokens?.accessTokenExpiresAt ?? 0) - now) / 1000)),
  };
}

/**
 * JWT は必ず eyJ（`{"` を Base64URL にした文字列）で始まります。
 * 応答にトークンが混ざっていないかを機械的に見つけるための簡易検査です。
 */
export function containsJwt(payload: unknown): boolean {
  return JSON.stringify(payload).includes("eyJ");
}

/**
 * 出口で検査するミドルウェア。ハンドラが返した本文に JWT が混ざっていたら 500 で止めます。
 * 実装を直すのとは別の価値があります。どのハンドラを書き足しても検査が効くからです。
 */
export function jwtLeakGuard(): MiddlewareHandler {
  return async (c, next) => {
    await next();
    const type = c.res.headers.get("content-type") ?? "";
    if (!type.includes("application/json")) {
      return;
    }
    // 本文は 1 度しか読めないので、複製して読む（元のレスポンスはそのまま返す）
    const body: unknown = await c.res.clone().json();
    if (containsJwt(body)) {
      c.res = new Response(JSON.stringify({ error: "token_leak_detected" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });
    }
  };
}

/** leaky と safe の両方に同じミドルウェアを当てて、挙動の差を見ます */
export async function reportGuard(session: RpSession): Promise<readonly string[]> {
  const lines: string[] = [];
  for (const mode of ["safe", "leaky"] as const) {
    const app = new Hono();
    app.use("*", jwtLeakGuard());
    app.get("/me", (c) => c.json(buildMePayload(session, mode, session.createdAt)));
    const res = await app.request("/me");
    const body = (await res.json()) as Record<string, unknown>;
    lines.push(`${mode}: status=${res.status} body のキー=${Object.keys(body).sort().join(",")}`);
  }
  return lines;
}
