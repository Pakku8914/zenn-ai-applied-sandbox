// セッション 13: private_key_jwt（RFC 7523）の assertion を組み立てます。
// 本書の realm の batch-worker は client_secret 方式で登録されているため、Keycloak には送りません。
// 認可サーバー側の検証は練習問題 6 で自分の手で作ります。
import { randomUUID } from "node:crypto";
import { SignJWT, exportJWK, generateKeyPair } from "jose";
import type { JWK } from "jose";
import { TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";
import { BATCH_CLIENT_ID } from "./batch-worker-client.js";

/** client_assertion_type に入れる固定値。これ以外の値は使いません */
export const CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer";
export const ASSERTION_ALG = "RS256";

export type AssertionOptions = {
  readonly clientId?: string;
  /** 宛先。トークンエンドポイントの URL か issuer を入れます */
  readonly audience?: string;
  readonly jti?: string;
  readonly iat?: number;
  readonly lifetimeSeconds?: number;
};

export type AssertionSigner = {
  /** 認可サーバーに登録する公開鍵。秘密鍵は外に出しません */
  readonly publicJwk: JWK;
  readonly build: (options?: AssertionOptions) => Promise<string>;
};

export async function createAssertionSigner(kid = "batch-worker-key-1"): Promise<AssertionSigner> {
  const { privateKey, publicKey } = await generateKeyPair(ASSERTION_ALG, { extractable: true });
  const publicJwk = await exportJWK(publicKey);
  publicJwk.kid = kid; // どの鍵で検証するかを認可サーバーに伝えます（セッション 4 の JWKS と同じ考え方）

  const build = async (options: AssertionOptions = {}): Promise<string> => {
    const iat = options.iat ?? Math.floor(Date.now() / 1000);
    const clientId = options.clientId ?? BATCH_CLIENT_ID;
    return await new SignJWT({})
      .setProtectedHeader({ alg: ASSERTION_ALG, kid })
      .setIssuer(clientId) // iss も sub も「クライアント自身」
      .setSubject(clientId)
      .setAudience(options.audience ?? TOKEN_ENDPOINT) // 宛先。別の認可サーバーへの転用を防ぐ要
      .setJti(options.jti ?? randomUUID())
      .setIssuedAt(iat)
      // 1 回のトークン要求のためだけに作るので、寿命は短くします
      .setExpirationTime(iat + (options.lifetimeSeconds ?? 60))
      .sign(privateKey);
  };

  return { publicJwk, build };
}
