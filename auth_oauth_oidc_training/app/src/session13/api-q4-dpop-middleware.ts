// セッション 13 問題 4: verifyDpopProof() を Hono に組み込み、DPoP のトークンだけを受け付ける
// API を作ります（セッション 10 の bearerAuth() の DPoP 版）。
import { Hono } from "hono";
import { createMiddleware } from "hono/factory";
import type { Context } from "hono";
import type { JWTPayload } from "jose";
import { verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { audiencesOf, toAccessTokenClaims } from "../session10/api-service-claims.js";
import type { AccessTokenClaims } from "../session10/api-service-claims.js";
import { REALM_LABEL, toHeaderSafe } from "../session10/api-service-challenge.js";
import { ACCEPTED_PROOF_ALGS, ProofReplayGuard, confirmationThumbprint, verifyDpopProof } from "./api-service-dpop.js";

/** RFC 9449 のエラーコード。invalid_dpop_proof が DPoP 固有 */
export type DpopErrorCode = "invalid_request" | "invalid_token" | "invalid_dpop_proof" | "use_dpop_nonce";

/** WWW-Authenticate の値。スキームは DPoP で、algs で受け付ける方式を知らせます */
export function dpopChallenge(args: { error?: DpopErrorCode; description?: string } = {}): string {
  const params = [`realm="${REALM_LABEL}"`, `algs="${ACCEPTED_PROOF_ALGS.join(" ")}"`];
  if (args.error !== undefined) {
    params.push(`error="${args.error}"`);
    const safe = toHeaderSafe(args.description ?? "");
    if (safe !== "") params.push(`error_description="${safe}"`);
  }
  return `DPoP ${params.join(", ")}`;
}

/** 401 を 1 か所で組み立てます。日本語は本文へ、ASCII はヘッダへ（セッション 10 と同じ） */
export function rejectDpop(
  c: Context,
  args: { error?: DpopErrorCode; description?: string; message: string },
): Response {
  c.header("www-authenticate", dpopChallenge({ error: args.error, description: args.description }));
  c.header("cache-control", "no-store");
  return c.json({ error: args.error ?? "unauthenticated", message: args.message }, 401);
}

/** Authorization: DPoP <token> の形だけを受け付けます */
const DPOP_TOKEN = /^DPoP +([A-Za-z0-9\-._~+/]+=*)$/i;

export type ExtractedDpop =
  | { readonly ok: true; readonly token: string }
  | { readonly ok: false; readonly reason: "missing" | "wrong_scheme" | "malformed" };

export function extractDpopToken(header: string | undefined): ExtractedDpop {
  const value = (header ?? "").trim();
  if (value === "") return { ok: false, reason: "missing" };
  // 送信者制約付きトークンを Bearer スキームで出してはいけません（RFC 9449 §7.1）
  if (!/^DPoP($| )/i.test(value)) return { ok: false, reason: "wrong_scheme" };
  const token = DPOP_TOKEN.exec(value)?.[1];
  return token === undefined ? { ok: false, reason: "malformed" } : { ok: true, token };
}

export type DpopEnv = {
  Variables: {
    claims: AccessTokenClaims;
    /** 検証を通った鍵のサムプリント。ログに残せば持ち主を追えます */
    jkt: string;
    /** 検証を通った proof の中身。後続の段が nonce を読めます */
    proof: JWTPayload;
  };
};

export type DpopAuthOptions = {
  readonly verify?: (token: string) => Promise<JWTPayload>;
  readonly guard?: ProofReplayGuard;
  readonly now?: () => number;
};

const strictVerify = async (token: string): Promise<JWTPayload> => (await verifyAccessToken(token)).payload;

/** DPoP のアクセストークンだけを受け付けるミドルウェア */
export function dpopAuth(options: DpopAuthOptions = {}) {
  const verify = options.verify ?? strictVerify;
  const guard = options.guard ?? new ProofReplayGuard();
  const clock = options.now ?? (() => Math.floor(Date.now() / 1000));

  return createMiddleware<DpopEnv>(async (c, next) => {
    const extracted = extractDpopToken(c.req.header("authorization"));
    if (!extracted.ok) {
      // 資格情報が無いだけなら error を付けません（セッション 10 と同じ）
      if (extracted.reason === "missing") {
        return rejectDpop(c, { message: "DPoP 方式のアクセストークンが必要です" });
      }
      return rejectDpop(c, {
        error: extracted.reason === "wrong_scheme" ? "invalid_token" : "invalid_request",
        description: `The Authorization header is not acceptable (${extracted.reason})`,
        message: "DPoP スキームで出し直してください",
      });
    }

    const proof = c.req.header("dpop");
    // 複数の DPoP ヘッダは 1 行にまとめられて届くので、カンマで気づけます
    if (proof === undefined || proof.trim() === "" || proof.includes(",")) {
      return rejectDpop(c, {
        error: "invalid_dpop_proof",
        description: "Exactly one DPoP proof is required",
        message: "DPoP ヘッダをちょうど 1 つ付けてください",
      });
    }

    let claims: AccessTokenClaims;
    try {
      claims = toAccessTokenClaims(await verify(extracted.token));
    } catch {
      return rejectDpop(c, {
        error: "invalid_token",
        description: "The access token is not valid",
        message: "アクセストークンを受け付けられません",
      });
    }

    const expectedThumbprint = confirmationThumbprint(claims);
    if (expectedThumbprint === undefined) {
      // 署名は本物でも、鍵に縛られていないトークンは受け付けません
      return rejectDpop(c, {
        error: "invalid_token",
        description: "The access token is not sender constrained",
        message: "このトークンは鍵に縛られていません",
      });
    }

    const result = await verifyDpopProof({
      proof,
      method: c.req.method,
      url: c.req.url,
      accessToken: extracted.token,
      expectedThumbprint,
      now: clock(),
      guard,
    });
    if (!result.ok) {
      return rejectDpop(c, {
        error: "invalid_dpop_proof",
        description: `The DPoP proof is not acceptable (${result.reason})`,
        message: "DPoP の証明を受け付けられません",
      });
    }

    c.set("claims", claims);
    c.set("jkt", result.jkt);
    c.set("proof", result.payload);
    await next();
  });
}

/** 夜間バッチが読む注文の一覧（セッション 2 と同じ ID） */
const ORDERS = ["order-1001", "order-1002", "order-1003", "order-2001"];

export function createDpopApi(options: DpopAuthOptions = {}): Hono<DpopEnv> {
  const app = new Hono<DpopEnv>();

  app.get("/health", (c) => c.json({ status: "ok", service: "api-service", accepts: "DPoP" }));

  // ここから下の /api/* は鍵の持ち主のリクエストだけが通ります
  app.use("/api/*", dpopAuth(options));

  // jkt を応答に載せると、誰の鍵で送られたかを監査で追えます
  app.get("/api/summary", (c) => {
    const claims = c.get("claims");
    return c.json({ client: claims.azp ?? null, audiences: audiencesOf(claims), jkt: c.get("jkt") });
  });

  app.get("/api/orders", (c) => c.json({ orders: ORDERS, client: c.get("claims").azp ?? null }));

  return app;
}
