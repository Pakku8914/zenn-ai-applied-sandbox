// セッション 13 問題 3: 3 本のバッチを 1 つのサービスアカウントで動かしたときの権限を棚卸し。
import { NIGHTLY_ORDER_SUMMARY, auditServiceAccount } from "./batch-worker-scope-audit.js";
import type { AuditReport, JobManifest, ServiceAccountFacts } from "./batch-worker-scope-audit.js";

/** 夜間に動く 3 本のバッチ。必要な権限はそれぞれ違います */
export const JOBS: readonly JobManifest[] = [
  NIGHTLY_ORDER_SUMMARY,
  { job: "refund-batch", requiredScopes: ["orders:read", "orders:write"], requiredAudiences: ["api-service"] },
  { job: "mail-sender", requiredScopes: ["email"], requiredAudiences: ["api-service"] },
];

export function auditAll(jobs: readonly JobManifest[], facts: ServiceAccountFacts): readonly AuditReport[] {
  return jobs.map((job) => auditServiceAccount(job, facts));
}

export type Action = {
  readonly action: "add-scope" | "add-audience" | "remove-scope";
  readonly target: string;
};

/**
 * 報告を「やること」に翻訳します。
 * 足りないものを足す作業（add）を先に、余っているものを外す作業（remove）を後に並べます。
 * 先に外すと、バッチが動かない時間が生まれるためです。
 */
export function remediation(report: AuditReport): readonly Action[] {
  return [
    ...report.missingScopes.map((target): Action => ({ action: "add-scope", target })),
    ...report.missingAudiences.map((target): Action => ({ action: "add-audience", target })),
    ...report.extraScopes.map((target): Action => ({ action: "remove-scope", target })),
  ];
}

export type SplitAdvice = {
  readonly advice: "share" | "separate";
  readonly distinctScopeSets: number;
  readonly reason: string;
};

/** 必要な権限の集合が 2 種類以上あるなら、サービスアカウントを分けます */
export function splitAdvice(jobs: readonly JobManifest[] = JOBS): SplitAdvice {
  const sets = new Set(jobs.map((job) => [...job.requiredScopes].sort().join(" ")));
  const distinctScopeSets = sets.size;
  return distinctScopeSets > 1
    ? {
        advice: "separate",
        distinctScopeSets,
        reason: `必要な権限の集合が ${distinctScopeSets} 種類あるため、1 つのアカウントに寄せると最も強い権限に合わせることになります`,
      }
    : {
        advice: "share",
        distinctScopeSets,
        reason: "すべてのバッチが同じ権限で足りるため、1 つのサービスアカウントで運用できます",
      };
}

/** 報告を 1 行 1 バッチの要約にします（そのまま作業チケットの説明に貼れる形） */
export function summarize(report: AuditReport): string {
  const actions = remediation(report).map((action) => `${action.action}:${action.target}`);
  return `${report.job} [${report.verdict}] ${actions.length === 0 ? "対応不要" : actions.join(" / ")}`;
}
