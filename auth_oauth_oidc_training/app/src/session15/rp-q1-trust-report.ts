// 問題1: 信頼関係の材料がそろっているかを表にする。
// 「IdP を登録する設定に何を書き写すのか」を、discovery から機械的に洗い出します。
import { TRUST_MATERIALS, checkTrust } from "./bookstore-sso-actors.js";
import type { TrustMaterial } from "./bookstore-sso-actors.js";

export type TrustRow = {
  readonly kind: TrustMaterial;
  readonly label: string;
  readonly satisfied: boolean;
  /** OIDC での採りどころ */
  readonly oidc: string;
  /** SAML での採りどころ */
  readonly saml: string;
};

/** checkTrust の判定結果に、材料の説明（TRUST_MATERIALS）を突き合わせます */
export function trustRows(
  config: Readonly<Record<string, unknown>>,
  registeredClientId: string | undefined,
): readonly TrustRow[] {
  return checkTrust(config, registeredClientId).map((check) => {
    const doc = TRUST_MATERIALS.find((material) => material.kind === check.kind);
    if (doc === undefined) {
      throw new Error(`説明の無い材料です: ${check.kind}`);
    }
    return {
      kind: check.kind,
      label: doc.label,
      satisfied: check.satisfied,
      oidc: doc.oidc,
      saml: doc.saml,
    };
  });
}

export function trustReport(
  config: Readonly<Record<string, unknown>>,
  registeredClientId: string | undefined,
): string {
  const header = "| 材料 | そろっているか | OIDC での採りどころ | SAML での採りどころ |";
  const divider = "| :--- | :--- | :--- | :--- |";
  const rows = trustRows(config, registeredClientId).map(
    (row) => `| ${row.label} | ${row.satisfied ? "○" : "×"} | ${row.oidc} | ${row.saml} |`,
  );
  return [header, divider, ...rows].join("\n");
}

/** 設定に進めない理由。空配列なら、必要な情報はそろっています */
export function blockers(
  config: Readonly<Record<string, unknown>>,
  registeredClientId: string | undefined,
): readonly string[] {
  return trustRows(config, registeredClientId)
    .filter((row) => !row.satisfied)
    .map((row) => `${row.label}が分からない（OIDC なら ${row.oidc} を確認する）`);
}
