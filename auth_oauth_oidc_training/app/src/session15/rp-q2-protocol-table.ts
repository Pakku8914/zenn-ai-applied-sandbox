// 問題2: SAML と OIDC の比較表を作り、3 つの提携先について方式を選ぶ。
import { chooseProtocol, factsOf } from "./bookstore-saml-oidc.js";
import type { FederationProtocol, FederationRequirement, ProtocolFacts } from "./bookstore-saml-oidc.js";

export type Axis = {
  readonly label: string;
  readonly pick: (facts: ProtocolFacts) => string;
};

/** 比較の軸。表の行の順序はここで決めます */
export const AXES: readonly Axis[] = [
  { label: "伝送方式", pick: (facts) => facts.transport },
  { label: "データ形式", pick: (facts) => facts.dataFormat },
  { label: "署名の単位", pick: (facts) => facts.signatureScope },
  { label: "向いている用途", pick: (facts) => facts.fit },
  { label: "実装の重さ", pick: (facts) => facts.weight },
];

export function comparisonTable(): string {
  const saml = factsOf("saml2");
  const oidc = factsOf("oidc");
  const lines = [`| 軸 | ${saml.label} | ${oidc.label} |`, "| :--- | :--- | :--- |"];
  for (const axis of AXES) {
    lines.push(`| ${axis.label} | ${axis.pick(saml)} | ${axis.pick(oidc)} |`);
  }
  return lines.join("\n");
}

export type NamedCase = {
  readonly name: string;
  readonly req: FederationRequirement;
};

/** 3 つの提携先。事実だけを書き、判断は chooseProtocol に任せます */
export const PARTNER_CASES: readonly NamedCase[] = [
  {
    name: "大手チェーン（情報システム部門あり）",
    req: { partnerSupports: ["saml2"], hasNativeApp: false, needsApiToken: true, partnerPolicy: "saml2" },
  },
  {
    name: "小規模書店（クラウドの ID 管理を使っている）",
    req: { partnerSupports: ["saml2", "oidc"], hasNativeApp: true, needsApiToken: true, partnerPolicy: "none" },
  },
  {
    name: "個人経営の書店（ID 管理はまだ無い）",
    req: { partnerSupports: [], hasNativeApp: false, needsApiToken: false, partnerPolicy: "none" },
  },
];

export type Decision = {
  readonly name: string;
  readonly protocol: FederationProtocol | "none";
  readonly reason: string;
};

export const decisionLog = (cases: readonly NamedCase[] = PARTNER_CASES): readonly Decision[] =>
  cases.map((entry) => {
    const choice = chooseProtocol(entry.req);
    return { name: entry.name, protocol: choice.protocol, reason: choice.reason };
  });

export function decisionTable(cases: readonly NamedCase[] = PARTNER_CASES): string {
  const lines = ["| 提携先 | 選ぶ方式 | 理由 |", "| :--- | :--- | :--- |"];
  for (const decision of decisionLog(cases)) {
    lines.push(`| ${decision.name} | ${decision.protocol} | ${decision.reason} |`);
  }
  return lines.join("\n");
}
