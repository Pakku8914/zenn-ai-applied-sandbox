// セッション 13: DPoP（RFC 9449）の鍵と証明（proof）を作る共通の道具。
// 秘密鍵はこのモジュールの中に閉じ込め、外に出すのは「公開鍵」と「proof を作る関数」だけです。
import { createHash, randomUUID } from "node:crypto";
import { SignJWT, calculateJwkThumbprint, exportJWK, generateKeyPair } from "jose";
import type { JWK, JWTPayload } from "jose";

/** 本章で使う proof の署名方式。discovery が申告している 10 方式のうちの 1 つです */
export const DPOP_ALG = "ES256";

/** proof に入れる材料。htm と htu が入るので、1 つの proof は 1 つのリクエストにしか使えません */
export type ProofRequest = {
  /** HTTP メソッド */
  readonly htm: string;
  /** クエリとフラグメントを除いたリクエスト URL */
  readonly htu: string;
  /** 同時に送るアクセストークン。ハッシュ（ath）として proof に入れます */
  readonly accessToken?: string;
  /** リソースサーバーから渡された nonce（練習問題 4 で使います） */
  readonly nonce?: string;
  /** 発行時刻（epoch 秒）。既定は現在時刻 */
  readonly iat?: number;
  /** 使い回しの実験のために、jti を外から固定できるようにしてあります */
  readonly jti?: string;
};

export type DpopKey = {
  /** 公開鍵。proof のヘッダにそのまま載せます（kty・crv・x・y の 4 つ） */
  readonly publicJwk: JWK;
  /** 公開鍵の SHA-256 サムプリント。アクセストークンの cnf.jkt と一致します */
  readonly thumbprint: string;
  /** リクエスト 1 回につき 1 つの proof を作ります */
  readonly createProof: (request: ProofRequest) => Promise<string>;
};

/** アクセストークン本体の SHA-256 を base64url にした値（RFC 9449 の ath クレーム） */
export function accessTokenHash(accessToken: string): string {
  return createHash("sha256").update(accessToken).digest("base64url");
}

/**
 * DPoP 用の鍵ペアを作ります。
 * extractable: true を付けないと、鍵を JWK として書き出せません（proof のヘッダに載せられません）。
 */
export async function createDpopKey(): Promise<DpopKey> {
  const { privateKey, publicKey } = await generateKeyPair(DPOP_ALG, { extractable: true });
  const publicJwk = await exportJWK(publicKey);
  const thumbprint = await calculateJwkThumbprint(publicJwk, "sha256");

  const createProof = async (request: ProofRequest): Promise<string> => {
    const claims: JWTPayload = { htm: request.htm.toUpperCase(), htu: request.htu };
    if (request.accessToken !== undefined) claims["ath"] = accessTokenHash(request.accessToken);
    if (request.nonce !== undefined) claims["nonce"] = request.nonce;

    return await new SignJWT(claims)
      // typ で「これは DPoP の証明であって、アクセストークンではない」と宣言します
      .setProtectedHeader({ alg: DPOP_ALG, typ: "dpop+jwt", jwk: publicJwk })
      // jti は 1 回きりの識別子。受け取った側はこれを覚えて使い回しを拒めます
      .setJti(request.jti ?? randomUUID())
      .setIssuedAt(request.iat ?? Math.floor(Date.now() / 1000))
      .sign(privateKey);
  };

  // 秘密鍵は返しません。この関数の外から取り出せるのは公開鍵と proof だけです
  return { publicJwk, thumbprint, createProof };
}
