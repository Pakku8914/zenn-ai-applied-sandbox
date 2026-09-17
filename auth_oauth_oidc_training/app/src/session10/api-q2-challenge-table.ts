// 問題 2 の解答: 6 つの状況を「status・WWW-Authenticate・本文」に対応づけます。
import { bearerChallenge } from "./api-service-challenge.js";

export type Situation =
  | "ヘッダが無い"
  | "ヘッダの形が壊れている"
  | "期限が切れている"
  | "宛先（aud）が違う"
  | "署名が合わない"
  | "ロールが足りない";

export const SITUATIONS: readonly Situation[] = [
  "ヘッダが無い",
  "ヘッダの形が壊れている",
  "期限が切れている",
  "宛先（aud）が違う",
  "署名が合わない",
  "ロールが足りない",
];

export type Rejection = {
  status: 401 | 403;
  /** 403 では null（認証はできているので出し直しを促さない） */
  challenge: string | null;
  bodyError: string;
};

/** 状況 → 返すべき応答。ここを 1 か所にまとめると、実装のブレがなくなります */
export function describeRejection(situation: Situation, realm = "api-service"): Rejection {
  switch (situation) {
    case "ヘッダが無い":
      // 資格情報が無いだけなので error は付けない（RFC 6750 §3.1）
      return { status: 401, challenge: bearerChallenge(realm), bodyError: "unauthenticated" };
    case "ヘッダの形が壊れている":
      return {
        status: 401,
        challenge: bearerChallenge(realm, {
          error: "invalid_request",
          description: "The Authorization header is not in the Bearer <token> form",
        }),
        bodyError: "invalid_request",
      };
    case "期限が切れている":
      return {
        status: 401,
        challenge: bearerChallenge(realm, { error: "invalid_token", description: "The access token expired" }),
        bodyError: "invalid_token",
      };
    case "宛先（aud）が違う":
      return {
        status: 401,
        challenge: bearerChallenge(realm, { error: "invalid_token", description: "The aud claim did not match" }),
        bodyError: "invalid_token",
      };
    case "署名が合わない":
      return {
        status: 401,
        challenge: bearerChallenge(realm, {
          error: "invalid_token",
          description: "The signature does not match the signing key",
        }),
        bodyError: "invalid_token",
      };
    case "ロールが足りない":
      // 認証はできている。出し直しても結果は変わらないのでチャレンジを返さない
      return { status: 403, challenge: null, bodyError: "forbidden" };
  }
}

/** ヘッダに入れてよい文字だけでできているか（RFC 6750 が許す範囲） */
export function isHeaderSafe(value: string): boolean {
  return /^[\x20-\x7E]*$/.test(value) && !value.includes("\\") && (value.match(/"/g) ?? []).length % 2 === 0;
}

export function toMarkdownTable(realm = "api-service"): string {
  const head = "| 状況 | status | WWW-Authenticate | 本文の error |\n| :--- | :--- | :--- | :--- |";
  const body = SITUATIONS.map((situation) => {
    const rejection = describeRejection(situation, realm);
    return `| ${situation} | ${rejection.status} | ${rejection.challenge ?? "付けない"} | ${rejection.bodyError} |`;
  }).join("\n");
  return `${head}\n${body}`;
}
