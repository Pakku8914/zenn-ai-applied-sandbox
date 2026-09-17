// 練習問題 3: aud を検証する API と検証しない API に同じトークンを送り、トークン置換が成立するかを監査する。
import type { Hono } from "hono";
import type { JWTPayload } from "jose";
import { decodeJwtPart } from "../test-helpers/headless-login.js";
import { audiencesOf } from "../session10/api-service-claims.js";
import type { ApiEnv } from "../session10/api-service-claims.js";

export type SubstitutionRow = {
  readonly label: string;
  readonly audiences: string[];
  readonly strictStatus: number;
  readonly looseStatus: number;
  /** aud を検証しない API だけが通す ＝ トークン置換が成立している */
  readonly substituted: boolean;
};

const auth = (token: string): { headers: Record<string, string> } => ({
  headers: { authorization: `Bearer ${token}` },
});

/** 1 本のトークンを、厳格な API と緩い API の両方に送って結果を突き合わせます */
export async function auditToken(
  label: string,
  token: string,
  strictApp: Hono<ApiEnv>,
  looseApp: Hono<ApiEnv>,
): Promise<SubstitutionRow> {
  const audiences = audiencesOf(decodeJwtPart<JWTPayload>(token, 1)).slice().sort();
  const strictStatus = (await strictApp.request("/api/whoami", auth(token))).status;
  const looseStatus = (await looseApp.request("/api/whoami", auth(token))).status;
  return { label, audiences, strictStatus, looseStatus, substituted: strictStatus === 401 && looseStatus === 200 };
}

/** 複数のトークンをまとめて監査します */
export async function auditTokens(
  tokens: readonly { label: string; token: string }[],
  strictApp: Hono<ApiEnv>,
  looseApp: Hono<ApiEnv>,
): Promise<SubstitutionRow[]> {
  const rows: SubstitutionRow[] = [];
  for (const { label, token } of tokens) {
    rows.push(await auditToken(label, token, strictApp, looseApp));
  }
  return rows;
}
