// PKCE（RFC 7636）の code_verifier と code_challenge を作る。
import { createHash, randomBytes } from "node:crypto";

/**
 * code_verifier から S256 の code_challenge を計算します。
 * 仕様は BASE64URL(SHA256(ASCII(code_verifier)))。ハッシュなので逆算はできません。
 */
export function challengeFor(codeVerifier: string): string {
  return createHash("sha256").update(codeVerifier, "ascii").digest().toString("base64url");
}

/** 使い捨ての code_verifier と、それに対応する code_challenge を 1 組作ります */
export function createPkcePair(): { codeVerifier: string; codeChallenge: string } {
  // 32 バイトの乱数を Base64URL にすると 43 文字。RFC 7636 が許す 43〜128 文字の下限です
  const codeVerifier = randomBytes(32).toString("base64url");
  return { codeVerifier, codeChallenge: challengeFor(codeVerifier) };
}
