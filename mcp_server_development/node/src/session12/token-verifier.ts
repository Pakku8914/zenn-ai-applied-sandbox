/**
 * アクセストークンの検証 ―― RS（＝MCP サーバー）の中核
 *
 * 検証する項目と順序（順序に理由があります）
 *   ① Authorization ヘッダーの形式（Bearer か）
 *   ② alg が許可リストに入っているか（RS256 だけ）／ヘッダーに鍵が同梱されていないか
 *   ③ kid に対応する公開鍵を JWKS から引く（取れなければ通さない＝fail closed）
 *   ④ 署名（★ クレームを読むより先に。中身は「本物と分かってから」読む）
 *   ⑤ iss（発行者）の完全一致
 *   ⑥ exp / nbf（時刻。時計ずれを許容する）
 *   ⑦ aud（★ このリソース向けのトークンか。ここを外すと 10 節の事故が起きる）
 *
 * ⚠️ 本番では実績あるライブラリ（jose など）を使ってください。
 *    ここで自作しているのは「何を検証しているか」を読めるようにするためです。
 */
import { type KeyObject, createHash } from "node:crypto";

import { decodeJws, publicKeyFromJwk, verifyJwsSignature } from "./jwt.js";
import type { AuthContext } from "./scopes.js";

export type VerifyFailure =
  | "missing_token"
  | "malformed_header"
  | "malformed_token"
  | "unsupported_alg"
  | "embedded_key"
  | "unknown_kid"
  | "bad_signature"
  | "issuer_mismatch"
  | "expired"
  | "not_yet_valid"
  | "audience_mismatch"
  | "jwks_unavailable";

export type VerifyOutcome =
  | { readonly ok: true; readonly context: AuthContext }
  | { readonly ok: false; readonly reason: VerifyFailure };

export type TokenVerifierOptions = {
  readonly issuer: string;
  /** このリソースの識別子。トークンの aud と完全一致を要求する */
  readonly audience: string;
  readonly jwksUri: string;
  /** 時計ずれの許容幅（秒）。分散環境では 0 にしない */
  readonly clockSkewSeconds?: number;
  readonly cacheTtlMs?: number;
  /** ❌ 実験専用。true にすると aud 検証を飛ばす（10 節でこれを使って事故を再現します） */
  readonly skipAudience?: boolean;
};

export type TokenVerifier = {
  verify(authorization: string | undefined): Promise<VerifyOutcome>;
};

/** 未知の kid を送り続けられても JWKS を取りに行きすぎないための下限間隔 */
const MIN_REFETCH_INTERVAL_MS = 10_000;

export function createTokenVerifier(options: TokenVerifierOptions): TokenVerifier {
  const clockSkew = options.clockSkewSeconds ?? 60;
  const cacheTtlMs = options.cacheTtlMs ?? 300_000;
  let cache: { keys: Map<string, KeyObject>; fetchedAt: number } | undefined;

  async function fetchJwks(): Promise<Map<string, KeyObject>> {
    const response = await fetch(options.jwksUri, { headers: { accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`JWKS の取得に失敗しました（status=${response.status}）`);
    }
    const payload: unknown = await response.json();
    const list = isRecord(payload) ? payload["keys"] : undefined;
    if (!Array.isArray(list)) {
      throw new Error("JWKS の形式が不正です（keys 配列がありません）");
    }
    const keys = new Map<string, KeyObject>();
    for (const entry of list) {
      if (!isRecord(entry)) {
        continue;
      }
      const { kty, n, e, kid } = entry;
      // 使えない鍵は黙って捨てる。想定外の kty を無理に解釈しない
      if (kty !== "RSA" || typeof n !== "string" || typeof e !== "string" || typeof kid !== "string") {
        continue;
      }
      keys.set(kid, publicKeyFromJwk({ kty, n, e }));
    }
    if (keys.size === 0) {
      throw new Error("JWKS に使える RSA 公開鍵がありません");
    }
    return keys;
  }

  /**
   * kid から公開鍵を引く。
   * 「知らない kid が来たら 1 回だけ取り直す」ようにしておくと、
   * 認可サーバーが鍵をローテーションしても RS を再起動せずに追随できます。
   */
  async function keyFor(kid: string): Promise<KeyObject | undefined> {
    const now = Date.now();
    const cached = cache;
    if (cached !== undefined) {
      const hit = cached.keys.get(kid);
      if (hit !== undefined && now - cached.fetchedAt < cacheTtlMs) {
        return hit;
      }
      if (now - cached.fetchedAt < MIN_REFETCH_INTERVAL_MS) {
        return hit;
      }
    }
    const keys = await fetchJwks();
    cache = { keys, fetchedAt: Date.now() };
    return keys.get(kid);
  }

  return {
    async verify(authorization) {
      // ① ヘッダーの形式
      if (authorization === undefined || authorization.trim() === "") {
        return { ok: false, reason: "missing_token" };
      }
      const token = extractBearerToken(authorization);
      if (token === undefined) {
        return { ok: false, reason: "malformed_header" };
      }

      const decoded = decodeJws(token);
      if (decoded === undefined) {
        return { ok: false, reason: "malformed_token" };
      }

      // ② alg は許可リスト方式。"none" や HMAC を受け入れると署名検証が無意味になる
      if (decoded.header["alg"] !== "RS256") {
        return { ok: false, reason: "unsupported_alg" };
      }
      // ヘッダーに鍵そのもの（jwk）や鍵の URL（jku）が入っていても絶対に使わない。
      // 「トークンが自分の検証鍵を持ってくる」のは、鍵の意味がなくなる典型的な攻撃です
      if (decoded.header["jwk"] !== undefined || decoded.header["jku"] !== undefined) {
        return { ok: false, reason: "embedded_key" };
      }
      const kid = decoded.header["kid"];
      if (typeof kid !== "string") {
        return { ok: false, reason: "malformed_token" };
      }

      // ③ 公開鍵の取得。取れないときは「通さない」（fail closed）
      let key: KeyObject | undefined;
      try {
        key = await keyFor(kid);
      } catch {
        return { ok: false, reason: "jwks_unavailable" };
      }
      if (key === undefined) {
        return { ok: false, reason: "unknown_kid" };
      }

      // ④ 署名。ここを通るまでクレームは「攻撃者が書いた文字列」だと考える
      if (!verifyJwsSignature(decoded, key)) {
        return { ok: false, reason: "bad_signature" };
      }

      const claims = decoded.payload;
      // ⑤ 発行者。信頼していない AS が発行したトークンは、署名が正しくても受け取らない
      if (claims["iss"] !== options.issuer) {
        return { ok: false, reason: "issuer_mismatch" };
      }

      // ⑥ 時刻。exp は必須。時計ずれを許容しないと、正しいトークンが弾かれる事故が起きる
      const now = Math.floor(Date.now() / 1000);
      const exp = claims["exp"];
      if (typeof exp !== "number" || exp + clockSkew < now) {
        return { ok: false, reason: "expired" };
      }
      const nbf = claims["nbf"];
      if (typeof nbf === "number" && nbf - clockSkew > now) {
        return { ok: false, reason: "not_yet_valid" };
      }

      // ⑦ オーディエンス。「このトークンは私宛か」―― 10 節の実験でここを外します
      if (options.skipAudience !== true && !audienceMatches(claims["aud"], options.audience)) {
        return { ok: false, reason: "audience_mismatch" };
      }

      const sub = claims["sub"];
      const scope = claims["scope"];
      const clientId = claims["client_id"];
      const jti = claims["jti"];
      return {
        ok: true,
        context: {
          subject: typeof sub === "string" ? sub : "(unknown)",
          clientId: typeof clientId === "string" ? clientId : undefined,
          // scope は「空白区切りの 1 本の文字列」。配列ではない（RFC 6749）
          scopes:
            typeof scope === "string" ? scope.split(" ").filter((value) => value.length > 0) : [],
          expiresAt: exp,
          tokenId: typeof jti === "string" ? jti : undefined,
          fingerprint: fingerprintToken(token),
        },
      };
    },
  };
}

/** Bearer スキームは大文字小文字を区別しない。トークン部分は base64url と "." だけ */
export function extractBearerToken(authorization: string | undefined): string | undefined {
  if (authorization === undefined) {
    return undefined;
  }
  return /^Bearer +([A-Za-z0-9._-]+)$/i.exec(authorization.trim())?.[1];
}

/** aud は文字列でも配列でもありうる。どちらでも「完全一致が 1 つあるか」で判定する */
export function audienceMatches(aud: unknown, expected: string): boolean {
  if (typeof aud === "string") {
    return aud === expected;
  }
  if (Array.isArray(aud)) {
    return aud.some((value) => value === expected);
  }
  return false;
}

/** トークン本体をログに出さないための相関 ID（ハッシュの先頭 8 文字） */
export function fingerprintToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex").slice(0, 8);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
