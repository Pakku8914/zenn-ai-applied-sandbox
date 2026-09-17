// セッション 13: サービスアカウントに付いている権限を棚卸しします。
// 「動くのに必要な権限」と「実際に載っている権限」を突き合わせ、足りないものと余っているものを出します。
import type { JWTPayload } from "jose";
import { verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { missingScopes, parseScope } from "../session07/rp-scope.js";
import { audiencesOf } from "../session10/api-service-claims.js";
import { requestClientCredentials } from "./batch-worker-client.js";

/** バッチ 1 本が「何をするために何が要るか」の宣言。コードと一緒に管理します */
export type JobManifest = {
  readonly job: string;
  readonly requiredScopes: readonly string[];
  readonly requiredAudiences: readonly string[];
};

/** トークンに実際に載っていた権限 */
export type ServiceAccountFacts = {
  readonly client: string;
  readonly scopes: readonly string[];
  readonly audiences: readonly string[];
  /** resource_access に現れたクライアント名。サービスアカウントには account が付きます */
  readonly resourceClients: readonly string[];
};

export type AuditVerdict = "ok" | "insufficient" | "excessive" | "mismatched";

export type AuditReport = {
  readonly job: string;
  readonly client: string;
  readonly missingScopes: readonly string[];
  readonly extraScopes: readonly string[];
  readonly missingAudiences: readonly string[];
  readonly verdict: AuditVerdict;
};

/** 夜間バッチ「前日の注文を集計する」が必要とする権限の宣言 */
export const NIGHTLY_ORDER_SUMMARY: JobManifest = {
  job: "nightly-order-summary",
  requiredScopes: ["orders:read"],
  requiredAudiences: ["api-service"],
};

/** 検証済みのペイロードから、棚卸しに使う事実だけを取り出します */
export function factsFromPayload(payload: JWTPayload): ServiceAccountFacts {
  const resourceAccess = payload["resource_access"];
  return {
    client: typeof payload["azp"] === "string" ? payload["azp"] : "",
    scopes: parseScope(typeof payload["scope"] === "string" ? payload["scope"] : "").sort(),
    audiences: audiencesOf(payload).slice().sort(),
    resourceClients:
      typeof resourceAccess === "object" && resourceAccess !== null ? Object.keys(resourceAccess).sort() : [],
  };
}

/** 宣言と実物を突き合わせます。過剰な権限は「今は害が無くても、いつか使われる」ものとして報告します */
export function auditServiceAccount(manifest: JobManifest, facts: ServiceAccountFacts): AuditReport {
  const missing = missingScopes(facts.scopes.join(" "), manifest.requiredScopes);
  const extra = facts.scopes.filter((scope) => !manifest.requiredScopes.includes(scope));
  const missingAudiences = manifest.requiredAudiences.filter((audience) => !facts.audiences.includes(audience));
  const short = missing.length > 0 || missingAudiences.length > 0;
  const over = extra.length > 0;
  return {
    job: manifest.job,
    client: facts.client,
    missingScopes: missing,
    extraScopes: extra,
    missingAudiences,
    verdict: short && over ? "mismatched" : short ? "insufficient" : over ? "excessive" : "ok",
  };
}

/** Client Credentials でトークンを取り、検証してから中身を棚卸しします */
export async function fetchServiceAccountFacts(): Promise<ServiceAccountFacts> {
  const { accessToken } = await requestClientCredentials();
  // 自分が受け取ったトークンでも、中身を読む前に必ず検証します（セッション 4）
  const { payload } = await verifyAccessToken(accessToken);
  return factsFromPayload(payload);
}
