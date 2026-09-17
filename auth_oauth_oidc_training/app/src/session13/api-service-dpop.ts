// セッション 13: リソースサーバー側の DPoP 検証。
// セッション 4・10 の「トークンが本物か」に、「この鍵の持ち主が送ってきたか」を足します。
// HTTP に組み込むミドルウェアは練習問題 4 で作ります。ここは純粋な判定だけです。
import { calculateJwkThumbprint, importJWK, jwtVerify } from "jose";
import type { JWK, JWTPayload } from "jose";
import { accessTokenHash } from "./bookstore-dpop.js";

/** 受け付ける proof の署名方式。ヘッダの alg を信じず、こちらで決めます（セッション 4 と同じ作法） */
export const ACCEPTED_PROOF_ALGS: readonly string[] = ["ES256"];
/** proof の iat をどれだけ過去・未来まで許すか（秒） */
export const PROOF_IAT_WINDOW = 30;

export type ProofReason =
  | "proof_malformed"
  | "proof_signature"
  | "thumbprint_mismatch"
  | "htm_mismatch"
  | "htu_mismatch"
  | "ath_mismatch"
  | "iat_out_of_window"
  | "jti_replayed";

export type ProofResult =
  | { readonly ok: true; readonly jkt: string; readonly payload: JWTPayload }
  | { readonly ok: false; readonly reason: ProofReason };

/** 使い終わった jti を覚えておく入れ物。同じ proof の 2 回目を拒みます */
export class ProofReplayGuard {
  private readonly seen = new Map<string, number>();
  private readonly windowSeconds: number;

  constructor(windowSeconds: number = PROOF_IAT_WINDOW) {
    this.windowSeconds = windowSeconds;
  }

  /** 初めて見た jti なら true。すでに見ていれば false */
  accept(jti: string, now: number): boolean {
    // iat の窓を過ぎた jti は、もう proof として受け付けないので覚えておく必要がありません
    for (const [key, at] of this.seen) {
      if (at + this.windowSeconds * 2 < now) this.seen.delete(key);
    }
    if (this.seen.has(jti)) return false;
    this.seen.set(jti, now);
    return true;
  }

  get size(): number {
    return this.seen.size;
  }
}

/** 受け取った jwk を鵜呑みにせず、ES256 の公開鍵として必要な 4 つだけを取り出します */
export function toPublicJwk(value: unknown): JWK | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const { kty, crv, x, y } = value as Record<string, unknown>;
  if (typeof kty !== "string" || typeof crv !== "string") return undefined;
  if (typeof x !== "string" || typeof y !== "string") return undefined;
  if (kty !== "EC" || crv !== "P-256") return undefined;
  return { kty, crv, x, y };
}

type ProofHeader = { alg?: unknown; typ?: unknown; jwk?: unknown };

/** 署名を確かめる前のヘッダは「主張」にすぎません。形だけ読み取ります */
function decodeProofHeader(proof: string): ProofHeader | undefined {
  const part = proof.split(".")[0];
  if (part === undefined || part === "") return undefined;
  try {
    const decoded: unknown = JSON.parse(Buffer.from(part, "base64url").toString());
    if (typeof decoded !== "object" || decoded === null) return undefined;
    return decoded as ProofHeader;
  } catch {
    return undefined;
  }
}

/** htu とリクエスト URL は、クエリとフラグメントを落として比べます（RFC 9449） */
export function sameRequestUrl(claimed: string, actual: string): boolean {
  try {
    const a = new URL(claimed);
    const b = new URL(actual);
    a.search = a.hash = "";
    b.search = b.hash = "";
    return a.toString() === b.toString();
  } catch {
    return false;
  }
}

/** アクセストークンの cnf.jkt。送信者制約が付いていなければ undefined */
export function confirmationThumbprint(claims: JWTPayload): string | undefined {
  const cnf = claims["cnf"];
  if (typeof cnf !== "object" || cnf === null) return undefined;
  const jkt = (cnf as Record<string, unknown>)["jkt"];
  return typeof jkt === "string" ? jkt : undefined;
}

export type ProofContext = {
  readonly proof: string;
  readonly method: string;
  readonly url: string;
  readonly accessToken: string;
  /** アクセストークンの cnf.jkt。この値と proof の公開鍵が一致しなければ拒否します */
  readonly expectedThumbprint: string;
  readonly now?: number;
  readonly guard?: ProofReplayGuard;
};

/** 5 つの観点を順に確かめます。1 つでも欠けると送信者制約は成り立ちません */
export async function verifyDpopProof(ctx: ProofContext): Promise<ProofResult> {
  const now = ctx.now ?? Math.floor(Date.now() / 1000);

  const header = decodeProofHeader(ctx.proof);
  if (header === undefined || header.typ !== "dpop+jwt") return { ok: false, reason: "proof_malformed" };
  if (typeof header.alg !== "string" || !ACCEPTED_PROOF_ALGS.includes(header.alg)) {
    return { ok: false, reason: "proof_malformed" };
  }
  const jwk = toPublicJwk(header.jwk);
  if (jwk === undefined) return { ok: false, reason: "proof_malformed" };

  let payload: JWTPayload;
  try {
    // proof の署名を確かめる鍵は、proof 自身が持ってきた公開鍵です（JWKS は引きません）
    const key = await importJWK(jwk, "ES256");
    payload = (await jwtVerify(ctx.proof, key, { algorithms: [...ACCEPTED_PROOF_ALGS], typ: "dpop+jwt" })).payload;
  } catch {
    return { ok: false, reason: "proof_signature" };
  }

  // 1. 鍵の同一性：proof の公開鍵は、アクセストークンが縛られている鍵か
  const jkt = await calculateJwkThumbprint(jwk, "sha256");
  if (jkt !== ctx.expectedThumbprint) return { ok: false, reason: "thumbprint_mismatch" };

  // 2. リクエストの同一性：この proof はこのメソッド・この URL のために作られたか
  if (payload["htm"] !== ctx.method.toUpperCase()) return { ok: false, reason: "htm_mismatch" };
  const claimedHtu = payload["htu"];
  if (typeof claimedHtu !== "string" || !sameRequestUrl(claimedHtu, ctx.url)) {
    return { ok: false, reason: "htu_mismatch" };
  }

  // 3. トークンとの結び付き：ath はいま届いたアクセストークンのハッシュか
  if (payload["ath"] !== accessTokenHash(ctx.accessToken)) return { ok: false, reason: "ath_mismatch" };

  // 4. 鮮度：作られてから時間が経ちすぎていないか
  if (typeof payload.iat !== "number" || Math.abs(now - payload.iat) > PROOF_IAT_WINDOW) {
    return { ok: false, reason: "iat_out_of_window" };
  }

  // 5. 一度きり：同じ jti の proof を 2 回受け付けない
  if (typeof payload.jti !== "string" || payload.jti === "") return { ok: false, reason: "proof_malformed" };
  if (ctx.guard !== undefined && !ctx.guard.accept(payload.jti, now)) {
    return { ok: false, reason: "jti_replayed" };
  }

  return { ok: true, jkt, payload };
}
