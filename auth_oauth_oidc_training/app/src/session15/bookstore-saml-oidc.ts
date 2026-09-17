// SAML 2.0 と OIDC を 5 つの軸で比べ、「どちらを選ぶか」を判定に落とします。
// どちらかが優れているという話ではありません。相手が開けている窓口に合わせるのが原則です。

export type FederationProtocol = "saml2" | "oidc";

export type ProtocolFacts = {
  readonly protocol: FederationProtocol;
  readonly label: string;
  /** 伝送方式（ブラウザが何を運ぶか） */
  readonly transport: string;
  /** データ形式 */
  readonly dataFormat: string;
  /** 署名の単位 */
  readonly signatureScope: string;
  /** 向いている用途 */
  readonly fit: string;
  /** 実装の重さ */
  readonly weight: string;
};

export const PROTOCOL_FACTS: readonly ProtocolFacts[] = [
  { protocol: "saml2", label: "SAML 2.0", transport: "ブラウザの自動 POST", dataFormat: "XML", signatureScope: "XML 文書の一部（Assertion 単位）", fit: "企業間・社内システム", weight: "重い（XML 正規化と署名検証）" },
  { protocol: "oidc", label: "OpenID Connect", transport: "リダイレクト（認可コード）", dataFormat: "JSON（JWT）", signatureScope: "トークン全体（3 部で 1 単位）", fit: "一般消費者向け・モバイル・API", weight: "軽い（JSON と Base64URL）" },
];

export function factsOf(protocol: FederationProtocol): ProtocolFacts {
  const found = PROTOCOL_FACTS.find((facts) => facts.protocol === protocol);
  if (found === undefined) {
    throw new Error(`未知のプロトコルです: ${protocol}`);
  }
  return found;
}

/** 連携を始めるときに集める 4 つの事実。ここに「好み」は入れません */
export type FederationRequirement = {
  /** 相手（IdP 側）が提供している方式 */
  readonly partnerSupports: readonly FederationProtocol[];
  /** 守る対象にモバイルアプリが含まれるか */
  readonly hasNativeApp: boolean;
  /** ログインの結果として API のアクセストークンも欲しいか */
  readonly needsApiToken: boolean;
  /** 相手の運用規定で方式が決まっているか（決まっていなければ "none"） */
  readonly partnerPolicy: FederationProtocol | "none";
};

export type ProtocolChoice = {
  readonly protocol: FederationProtocol | "none";
  readonly reason: string;
};

/**
 * 判定の順序に意味があります。
 * 「相手が開けている窓口」→「相手の運用規定」→「こちらの要件」の順に効かせます。
 * こちらの好みを先に置くと、相手が対応できない要求を出すことになります。
 */
export function chooseProtocol(req: FederationRequirement): ProtocolChoice {
  const supports = (protocol: FederationProtocol): boolean => req.partnerSupports.includes(protocol);
  const policy = req.partnerPolicy;

  if (req.partnerSupports.length === 0) {
    return { protocol: "none", reason: "相手が SSO の窓口を持っていない。まず相手に IdP を用意してもらう" };
  }
  if (policy !== "none" && supports(policy)) {
    return { protocol: policy, reason: "相手の運用規定で方式が決まっている。こちらの好みより相手の規定が先" };
  }
  if (!supports("oidc")) {
    return { protocol: "saml2", reason: "相手の窓口が SAML だけ。古いからではなく、開いている窓口がそこしかない" };
  }
  if (!supports("saml2")) {
    return { protocol: "oidc", reason: "相手の窓口が OIDC だけ" };
  }
  if (req.hasNativeApp || req.needsApiToken) {
    return { protocol: "oidc", reason: "モバイルアプリか API のアクセストークンが要る。SAML はどちらも想定していない" };
  }
  return { protocol: "oidc", reason: "どちらも選べる。実装が軽く、API の認可まで通せる OIDC を既定にする" };
}
