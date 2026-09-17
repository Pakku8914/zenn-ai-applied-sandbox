// 問題 6 の解答。openid-client に任せている ID トークンの検証を、自分の手で書き直します。
// 「ライブラリが黙ってやっていること」を数え上げるための課題です。
import { createRemoteJWKSet, jwtVerify } from "jose";
import { CLIENT_ID, ISSUER_INTERNAL } from "./rp-openid-config.js";

// JWKS の取得口は 1 回だけ作って使い回す（jose が取得結果をキャッシュする）
const jwks = createRemoteJWKSet(new URL(`${ISSUER_INTERNAL}/protocol/openid-connect/certs`));

export type ManualCheck = { name: string; passed: boolean };

/**
 * ID トークンを自前で検証します。渡した nonce は、認可リクエストで送った値です。
 * 戻り値は「検証項目と結果」の一覧で、1 つでも passed が false なら認証として扱ってはいけません。
 */
export async function verifyIdTokenManually(idToken: string, expectedNonce: string): Promise<ManualCheck[]> {
  try {
    const { payload } = await jwtVerify(idToken, jwks, {
      algorithms: ["RS256"], // ヘッダの alg を信じない
      issuer: ISSUER_INTERNAL, // 誰が名乗ったか
      audience: CLIENT_ID, // ID トークンの aud は web-app（api-service ではない）
      clockTolerance: 5, // 時計のずれの許容（秒）
    });
    return [
      // ここまでの 1 行で、署名・iss・aud・exp・nbf の 5 項目が済んでいる
      { name: "署名・iss・aud・exp", passed: true },
      // 以下は jose が見てくれないので、自分で確かめる
      { name: "nonce が送った値と同じ", passed: payload["nonce"] === expectedNonce },
      { name: "azp が自分のクライアント ID", passed: payload["azp"] === CLIENT_ID },
      { name: "sub がある", passed: typeof payload.sub === "string" && payload.sub !== "" },
      { name: "iat が未来ではない", passed: typeof payload.iat === "number" && payload.iat <= Math.floor(Date.now() / 1000) + 5 },
    ];
  } catch {
    // 署名・iss・aud・exp のいずれかで落ちた場合。理由の詳細は利用者には返さない
    return [{ name: "署名・iss・aud・exp", passed: false }];
  }
}

/** 落ちた検証項目の名前だけを取り出す（全部通れば空の配列） */
export function failedNames(checks: ManualCheck[]): string[] {
  return checks.filter((check) => !check.passed).map((check) => check.name);
}
