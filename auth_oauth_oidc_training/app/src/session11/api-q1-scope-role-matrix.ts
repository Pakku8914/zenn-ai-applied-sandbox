// 問題 1 の解答: スコープ（クライアントの権限）とロール（利用者の権限）の掛け算を表にします。
import type { Action } from "../session02/api-authz-decide.js";
import type { TokenFacts } from "./api-authz-claims.js";
import type { BookstoreDirectory } from "./api-authz-directory.js";
import { authorize } from "./api-authz-policy.js";
import type { ScopeRequirements } from "./api-authz-policy.js";

export type MatrixCase = {
  readonly label: string;
  readonly sub: string;
  readonly username: string;
  readonly scopes: readonly string[];
  readonly realmRoles: readonly string[];
  readonly clientRoles?: readonly string[];
  readonly action: Action;
  readonly orderId: string;
  /** 省略すると設計どおりの要件（orders:read / orders:write）になります */
  readonly requiredScopes?: ScopeRequirements;
};

export type MatrixRow = {
  readonly label: string;
  readonly httpStatus: 200 | 403;
  /** 応答に載せるエラーコード。許可のときは空文字 */
  readonly error: string;
  readonly stage: "scope" | "subject" | "granted";
  readonly missing: readonly string[];
};

/**
 * 判断材料を手で組み立てます。署名検証を通ったトークンから取り出した想定なので、
 * ここでは発行時刻・失効時刻は使いません（0 を入れておきます）。
 */
export function factsOf(item: MatrixCase): TokenFacts {
  return {
    sub: item.sub,
    username: item.username,
    scopes: item.scopes,
    realmRoles: [...item.realmRoles].sort(),
    clientRoles: [...(item.clientRoles ?? [])].sort(),
    issuedAt: 0,
    expiresAt: 0,
  };
}

/** 落ちた段を HTTP の応答に翻訳します。スコープ不足だけ別のコードになります */
export function toHttp(row: { allow: boolean; stage: MatrixRow["stage"] }): { httpStatus: 200 | 403; error: string } {
  if (row.allow) return { httpStatus: 200, error: "" };
  return { httpStatus: 403, error: row.stage === "scope" ? "insufficient_scope" : "forbidden" };
}

export function evaluateCases(
  cases: readonly MatrixCase[],
  directory: BookstoreDirectory,
): readonly MatrixRow[] {
  return cases.map((item) => {
    const order = directory.order(item.orderId);
    if (order === undefined) throw new Error(`知らない注文です: ${item.orderId}`);
    const facts = factsOf(item);
    const result = authorize(facts, item.action, order, {
      // 属性はトークンではなく API 側の台帳から渡す
      attributes: directory.attributesOf(item.sub),
      requiredScopes: item.requiredScopes,
    });
    const http = toHttp(result);
    return {
      label: item.label,
      httpStatus: http.httpStatus,
      error: http.error,
      stage: result.stage,
      missing: result.missing,
    };
  });
}

/** Markdown の表にして返します（章の答え合わせ用） */
export function toMarkdown(rows: readonly MatrixRow[]): string {
  const head = "| ケース | HTTP | エラー | 決まった段 |\n| :--- | :--- | :--- | :--- |";
  const body = rows
    .map((row) => `| ${row.label} | ${row.httpStatus} | ${row.error === "" ? "—" : row.error} | ${row.stage} |`)
    .join("\n");
  return `${head}\n${body}`;
}
