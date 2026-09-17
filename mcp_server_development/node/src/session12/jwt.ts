/**
 * JWS（JSON Web Signature）の最小実装 ―― 追加依存ゼロ
 *
 * ⚠️ 学習用です。本番では実績あるライブラリ（jose など）と JWKS を使ってください。
 *    理由は「アルゴリズム混同攻撃・鍵の取り違え・パディングの扱い」など、
 *    自作で踏みやすい落とし穴が実装済みだからです（6 節で 2 つだけ自分で塞ぎます）。
 *
 * ここで使うのは RS256（RSA-SHA256）です。秘密鍵で署名し、公開鍵で検証するので、
 * 「AS だけが発行でき、RS は検証だけできる」という役割分担が鍵の形で表現できます。
 */
import {
  type KeyObject,
  createHash,
  createPublicKey,
  createSign,
  createVerify,
} from "node:crypto";

/** JWS ヘッダー。alg は RS256 だけを使う（理由は 6 節） */
export type JwsHeader = { readonly alg: "RS256"; readonly typ: "JWT"; readonly kid: string };

/** アクセストークンに載せるクレーム */
export type TokenClaims = {
  /** 発行者。RS はこれを完全一致で検証する */
  readonly iss: string;
  /** 主体。「誰の権限で動いているか」 */
  readonly sub: string;
  /** 宛先。RS 自身の識別子と一致しなければ受け取ってはいけない */
  readonly aud: string | readonly string[];
  /** 失効時刻（UNIX 秒） */
  readonly exp: number;
  readonly iat: number;
  readonly nbf?: number;
  /** トークン固有の ID。監査ログの相関に使う */
  readonly jti?: string;
  /** 空白区切りのスコープ */
  readonly scope?: string;
  readonly client_id?: string;
};

export function base64UrlEncode(input: string | Buffer): string {
  const buffer = typeof input === "string" ? Buffer.from(input, "utf8") : input;
  return buffer.toString("base64url");
}

export function base64UrlDecode(input: string): Buffer {
  return Buffer.from(input, "base64url");
}

/** 署名対象は「ヘッダー.ペイロード」という 1 本の文字列。ここが JWS の核心 */
export function signJws(header: JwsHeader, claims: TokenClaims, privateKey: KeyObject): string {
  const signingInput = `${base64UrlEncode(JSON.stringify(header))}.${base64UrlEncode(JSON.stringify(claims))}`;
  const signature = createSign("RSA-SHA256").update(signingInput).sign(privateKey);
  return `${signingInput}.${base64UrlEncode(signature)}`;
}

export type DecodedJws = {
  readonly header: Record<string, unknown>;
  readonly payload: Record<string, unknown>;
  readonly signingInput: string;
  readonly signature: Buffer;
};

/**
 * 分解するだけ。検証はしない。
 * 「decode は誰でもできる（＝中身は秘密ではない）」ことを型で表しています。
 */
export function decodeJws(token: string): DecodedJws | undefined {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return undefined;
  }
  const [rawHeader, rawPayload, rawSignature] = parts;
  if (rawHeader === undefined || rawPayload === undefined || rawSignature === undefined) {
    return undefined;
  }
  try {
    const header: unknown = JSON.parse(base64UrlDecode(rawHeader).toString("utf8"));
    const payload: unknown = JSON.parse(base64UrlDecode(rawPayload).toString("utf8"));
    if (!isRecord(header) || !isRecord(payload)) {
      return undefined;
    }
    return {
      header,
      payload,
      signingInput: `${rawHeader}.${rawPayload}`,
      signature: base64UrlDecode(rawSignature),
    };
  } catch {
    return undefined;
  }
}

export function verifyJwsSignature(decoded: DecodedJws, publicKey: KeyObject): boolean {
  return createVerify("RSA-SHA256").update(decoded.signingInput).verify(publicKey, decoded.signature);
}

export type RsaJwk = {
  readonly kty: "RSA";
  readonly n: string;
  readonly e: string;
  readonly kid: string;
  readonly alg: "RS256";
  readonly use: "sig";
};

/** 公開鍵を JWKS で配れる形（JWK）に変換する */
export function toRsaJwk(publicKey: KeyObject): RsaJwk {
  const exported = publicKey.export({ format: "jwk" });
  const { kty, n, e } = exported;
  if (kty !== "RSA" || n === undefined || e === undefined) {
    throw new Error("RSA 公開鍵ではありません（JWK への変換に失敗しました）");
  }
  return { kty: "RSA", n, e, kid: jwkThumbprint(n, e), alg: "RS256", use: "sig" };
}

/**
 * RFC 7638 の JWK サムプリント。
 * 鍵の内容から決まるので、同じ鍵なら kid も同じ。連番にしないのは、
 * 鍵を差し替えたときに「古い kid が別の鍵を指す」事故を防ぐためです。
 */
export function jwkThumbprint(n: string, e: string): string {
  const canonical = JSON.stringify({ e, kty: "RSA", n });
  return createHash("sha256").update(canonical, "utf8").digest("base64url");
}

export function publicKeyFromJwk(jwk: { kty: string; n: string; e: string }): KeyObject {
  return createPublicKey({ key: { kty: jwk.kty, n: jwk.n, e: jwk.e }, format: "jwk" });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
