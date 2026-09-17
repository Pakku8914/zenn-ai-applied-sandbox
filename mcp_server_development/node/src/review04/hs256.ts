/**
 * HS256（HMAC-SHA256）による JWT の組み立てと分解 ―― 追加依存ゼロ
 *
 * ⚠️ 学習用です。本番では実績あるライブラリ（jose など）と非対称鍵（RS256）＋ JWKS を
 *    使ってください。セッション12 の本文は RS256 でした。ここで対称鍵にしているのは、
 *    鍵ペアの生成も HTTP も使わずに「決定的なトークン」を作れるようにするためです。
 *    検証すべき項目（署名・iss・exp・aud）と順序は RS256 とまったく同じです。
 */
import { createHmac, timingSafeEqual } from "node:crypto";

export type JwtHeader = { alg: string; typ: "JWT" };

export type JwtClaims = {
  iss: string;
  sub: string;
  aud: string | readonly string[];
  exp: number;
  iat: number;
  scope?: string;
  client_id?: string;
  jti?: string;
};

export function base64UrlEncode(input: string | Buffer): string {
  const buffer = typeof input === "string" ? Buffer.from(input, "utf8") : input;
  return buffer.toString("base64url");
}

export function base64UrlDecode(input: string): Buffer {
  return Buffer.from(input, "base64url");
}

/** 署名対象は「ヘッダー.ペイロード」という 1 本の文字列 */
export function hmacSignature(signingInput: string, secret: string): string {
  return createHmac("sha256", secret).update(signingInput, "utf8").digest("base64url");
}

export function signHs256(
  claims: JwtClaims,
  secret: string,
  header: JwtHeader = { alg: "HS256", typ: "JWT" },
): string {
  const signingInput = `${base64UrlEncode(JSON.stringify(header))}.${base64UrlEncode(JSON.stringify(claims))}`;
  return `${signingInput}.${hmacSignature(signingInput, secret)}`;
}

export type DecodedJwt = {
  header: Record<string, unknown>;
  payload: Record<string, unknown>;
  signingInput: string;
  signature: string;
};

/** 分解するだけ。検証はしない（decode は誰でもできる＝中身は秘密ではない） */
export function decodeJwt(token: string): DecodedJwt | undefined {
  const parts = token.split(".");
  if (parts.length !== 3) return undefined;
  const [rawHeader, rawPayload, rawSignature] = parts;
  if (rawHeader === undefined || rawPayload === undefined || rawSignature === undefined) {
    return undefined;
  }
  try {
    const header: unknown = JSON.parse(base64UrlDecode(rawHeader).toString("utf8"));
    const payload: unknown = JSON.parse(base64UrlDecode(rawPayload).toString("utf8"));
    if (!isRecord(header) || !isRecord(payload)) return undefined;
    return {
      header,
      payload,
      signingInput: `${rawHeader}.${rawPayload}`,
      signature: rawSignature,
    };
  } catch {
    return undefined;
  }
}

/** 署名の比較は定数時間で行う（長さが違う場合は比較せず false） */
export function signatureMatches(decoded: DecodedJwt, secret: string): boolean {
  const expected = Buffer.from(hmacSignature(decoded.signingInput, secret), "utf8");
  const actual = Buffer.from(decoded.signature, "utf8");
  if (expected.length !== actual.length) return false;
  return timingSafeEqual(expected, actual);
}

/** テスト用のトークン鋳造口。now を渡せるので時刻に依存しない検証ができる */
export type MintOptions = {
  secret: string;
  issuer: string;
  audience: string | readonly string[];
  subject: string;
  scope: string;
  /** 基準時刻（UNIX 秒）。テストから固定値を渡す */
  now: number;
  ttlSeconds?: number;
  header?: JwtHeader;
};

export function mintToken(options: MintOptions): string {
  const iat = options.now;
  return signHs256(
    {
      iss: options.issuer,
      sub: options.subject,
      aud: options.audience,
      exp: iat + (options.ttlSeconds ?? 300),
      iat,
      scope: options.scope,
    },
    options.secret,
    options.header ?? { alg: "HS256", typ: "JWT" },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
