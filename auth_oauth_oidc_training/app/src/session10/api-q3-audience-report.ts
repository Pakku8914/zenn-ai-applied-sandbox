// 問題 3 の解答: 3 種類のトークンの宛先（aud）を調べ、api-service が受け取るかどうかを表にします。
import type { JWTPayload } from "jose";
import { rejectReason, verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { audiencesOf } from "./api-service-claims.js";

export type AudienceRow = {
  label: string;
  /** 並べ替えた aud。文字列で届いても配列で届いても同じ形にそろえる */
  audiences: string[];
  /** トークンを受け取ったクライアント（azp） */
  authorizedParty: string | null;
  acceptedByApiService: boolean;
  reason: string;
};

export async function auditToken(label: string, token: string): Promise<AudienceRow> {
  const payload = decodeJwtPart<JWTPayload>(token, 1); // 署名を見ないデコード（表示のためだけ）
  const azp = payload["azp"];
  const row = {
    label,
    audiences: audiencesOf(payload).slice().sort(),
    authorizedParty: typeof azp === "string" ? azp : null,
  };
  try {
    await verifyAccessToken(token); // algorithms・issuer・audience・clockTolerance を全部指定した検証
    return { ...row, acceptedByApiService: true, reason: "-" };
  } catch (err) {
    return { ...row, acceptedByApiService: false, reason: rejectReason(err) };
  }
}

export async function auditTokens(tokens: readonly { label: string; token: string }[]): Promise<AudienceRow[]> {
  const rows: AudienceRow[] = [];
  for (const { label, token } of tokens) {
    rows.push(await auditToken(label, token));
  }
  return rows;
}

export function toMarkdownTable(rows: readonly AudienceRow[]): string {
  const head = "| トークン | aud（並べ替え） | azp | api-service が受け取るか | 理由 |\n| :--- | :--- | :--- | :--- | :--- |";
  const body = rows
    .map(
      (row) =>
        `| ${row.label} | ${row.audiences.join(", ")} | ${row.authorizedParty ?? "-"} | ${row.acceptedByApiService ? "受け取る" : "拒否"} | ${row.reason} |`,
    )
    .join("\n");
  return `${head}\n${body}`;
}
