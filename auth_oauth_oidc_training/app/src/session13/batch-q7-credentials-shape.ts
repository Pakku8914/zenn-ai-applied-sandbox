// セッション 13（前半）問題 2: Client Credentials の応答の形を確かめます。
// 「返らないもの」（refresh_token）と「型が揺れるもの」（aud）に注目し、
// 再取得の作戦が利用者のいるフローとどう違うのかを判定として残します。
import type { JWTPayload } from "jose";
import { verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { audiencesOf } from "../session10/api-service-claims.js";
import { requestClientCredentials } from "./batch-worker-client.js";

/** aud は文字列にも配列にもなります。どちらで届いたかを型として記録します */
export type AudienceKind = "array" | "string" | "absent";

export function audienceKind(rawAud: unknown): AudienceKind {
  if (Array.isArray(rawAud)) return "array";
  if (typeof rawAud === "string") return "string";
  return "absent";
}

/** 再取得の作戦。利用者がいないフローでは「もう一度取り直す」しかありません */
export type RenewalPlan = "re-request" | "refresh";

export function renewalPlan(hasRefreshToken: boolean): RenewalPlan {
  return hasRefreshToken ? "refresh" : "re-request";
}

export type CredentialShape = {
  readonly status: number;
  /** 返ってきたキー（並べ替え済み） */
  readonly keys: readonly string[];
  readonly tokenType: string;
  readonly hasRefreshToken: boolean;
  readonly expiresIn: number;
  /** aud がどの型で届いたか */
  readonly audienceKind: AudienceKind;
  /** audiencesOf() で配列にそろえた aud（並べ替え済み） */
  readonly audiences: readonly string[];
  readonly renewal: RenewalPlan;
};

/** トークンを 1 本取り、検証したうえで「応答の形」だけを取り出します */
export async function describeCredentials(): Promise<CredentialShape> {
  const result = await requestClientCredentials();
  // 自分が受け取ったトークンでも、中身を読む前に必ず検証します（セッション 4）
  const { payload } = await verifyAccessToken(result.accessToken);
  return {
    status: result.status,
    keys: result.keys,
    tokenType: result.tokenType,
    hasRefreshToken: result.hasRefreshToken,
    expiresIn: result.expiresIn,
    audienceKind: audienceKind((payload as JWTPayload)["aud"]),
    // 型が揺れる値は、比べる前に必ず配列へ正規化します（セッション 10 の audiencesOf）
    audiences: audiencesOf(payload).slice().sort(),
    renewal: renewalPlan(result.hasRefreshToken),
  };
}

/** 応答の形を 1 行にまとめます（そのまま運用手順書に貼れる形） */
export function summarizeShape(shape: CredentialShape): string {
  return [
    `token_type=${shape.tokenType}`,
    `refresh_token=${shape.hasRefreshToken ? "あり" : "なし"}`,
    `expires_in=${shape.expiresIn}`,
    `aud=${shape.audienceKind}(${shape.audiences.join(",")})`,
    `renewal=${shape.renewal}`,
  ].join(" ");
}
