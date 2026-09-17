// 問題6（発展・セッション15 前半）: 提携先 4 社について「今日開通させられるか」を、集めた事実から導く。
// 判定はすべて既存の関数に任せ、ここでは組み合わせと順序だけを決めます。
import { chooseProtocol } from "./bookstore-saml-oidc.js";
import type { FederationProtocol, FederationRequirement } from "./bookstore-saml-oidc.js";
import { earliestStage, failureFindings } from "./rp-q7-trust-failure-stage.js";
import type { FailureStage } from "./rp-q7-trust-failure-stage.js";
import { supportedStyles } from "./rp-q8-logout-capability.js";
import type { LogoutStyle } from "./rp-q8-logout-capability.js";
import { SAMPLE_PARTNER_DISCOVERY, buildBrokerConfig } from "./rp-q9-broker-config.js";

export type OnboardingInput = {
  readonly name: string;
  readonly req: FederationRequirement;
  /** 相手の discovery。SAML だけの相手や窓口が無い相手は null */
  readonly discovery: Readonly<Record<string, unknown>> | null;
  readonly registeredClientId: string | undefined;
  readonly alias: string;
};

export type Onboarding = {
  readonly name: string;
  readonly protocol: FederationProtocol | "none";
  /** 最初につまずく段階。開通できるなら "none" */
  readonly blockedAt: FailureStage | "none";
  /** ブローカー設定を今日書けるか。SAML には概念が無いので not-applicable */
  readonly broker: "ready" | "blocked" | "not-applicable";
  /** 出口。OIDC なら discovery の申告、SAML なら SLO、連携しないなら空 */
  readonly exit: readonly (LogoutStyle | "saml-slo")[];
  readonly openable: boolean;
  readonly todos: readonly string[];
};

const SCOPES = ["openid", "profile", "email"] as const;

/**
 * 判定の順序を固定します。
 * 方式 → 材料の充足 → ブローカー設定 → 出口 の順です。方式が決まらないと材料の採りどころも決まりません。
 */
export function planOnboarding(input: OnboardingInput): Onboarding {
  const protocol = chooseProtocol(input.req).protocol;
  const base = { name: input.name, protocol } as const;
  const todos: string[] = [];

  if (protocol === "none") {
    return { ...base, blockedAt: "setup", broker: "not-applicable", exit: [], openable: false, todos: ["相手に IdP を用意してもらう（連携の前提が無い）"] };
  }
  if (protocol === "saml2") {
    // SAML のメタデータは discovery ではありません。4 材料は XML から採ります
    const registered = input.registeredClientId !== undefined;
    if (!registered) {
      todos.push("SP として登録してもらう（entityID と ACS URL を渡す）");
    }
    todos.push("メタデータ XML を受け取り、entityID と証明書を取り込む");
    if (input.req.needsApiToken) {
      todos.push("API のアクセストークンは自分の realm で発行する（SAML では出ない）");
    }
    return { ...base, blockedAt: registered ? "none" : "callback", broker: "not-applicable", exit: ["saml-slo"], openable: registered, todos };
  }

  const discovery = input.discovery ?? {};
  const findings = failureFindings(discovery, input.registeredClientId);
  const built = buildBrokerConfig({
    localRealm: "bookstore",
    keycloakBase: "http://keycloak:8080",
    alias: input.alias,
    partnerDiscovery: discovery,
    clientId: input.registeredClientId,
    clientSecretRef: "PARTNER_BROKER_SECRET",
    scopes: SCOPES,
  });
  for (const finding of findings) {
    todos.push(`${finding.label}を相手から受け取る（${finding.symptom}）`);
  }
  if (!built.ok) {
    for (const problem of built.problems) {
      todos.push(problem);
    }
  }
  return {
    ...base,
    blockedAt: earliestStage(findings),
    broker: built.ok ? "ready" : "blocked",
    exit: supportedStyles(discovery),
    openable: built.ok,
    todos,
  };
}

/** 出口の申告まで含んだ見立ての discovery（bookstore realm の実測値と同じ形） */
export const PARTNER_DISCOVERY_FULL: Readonly<Record<string, unknown>> = {
  ...SAMPLE_PARTNER_DISCOVERY,
  end_session_endpoint: "http://keycloak:8080/realms/partner/protocol/openid-connect/logout",
  frontchannel_logout_supported: true,
  frontchannel_logout_session_supported: true,
  backchannel_logout_supported: true,
  backchannel_logout_session_supported: true,
  backchannel_token_delivery_modes_supported: ["poll", "ping"],
};

const req = (
  partnerSupports: readonly FederationProtocol[],
  hasNativeApp: boolean,
  needsApiToken: boolean,
  partnerPolicy: FederationProtocol | "none",
): FederationRequirement => ({ partnerSupports, hasNativeApp, needsApiToken, partnerPolicy });

export const ONBOARDING_INPUTS: readonly OnboardingInput[] = [
  { name: "大手チェーン", req: req(["saml2"], false, true, "saml2"), discovery: null, registeredClientId: "bookstore-sp", alias: "major-chain" },
  { name: "小規模書店", req: req(["saml2", "oidc"], true, true, "none"), discovery: PARTNER_DISCOVERY_FULL, registeredClientId: "bookstore-broker", alias: "small-shop" },
  { name: "取次（クライアント未発行）", req: req(["oidc"], false, false, "none"), discovery: SAMPLE_PARTNER_DISCOVERY, registeredClientId: undefined, alias: "distributor" },
  { name: "個人経営の書店", req: req([], false, false, "none"), discovery: null, registeredClientId: undefined, alias: "solo-shop" },
];

export const planAllOnboarding = (inputs: readonly OnboardingInput[] = ONBOARDING_INPUTS): readonly Onboarding[] =>
  inputs.map((input) => planOnboarding(input));

export function onboardingTable(inputs: readonly OnboardingInput[] = ONBOARDING_INPUTS): string {
  const lines = ["| 提携先 | 方式 | つまずく段階 | 出口 | 開通 | 次の作業 |", "| :--- | :--- | :--- | :--- | :--- | :--- |"];
  for (const plan of planAllOnboarding(inputs)) {
    const exit = plan.exit.length === 0 ? "―" : plan.exit.join(" / ");
    lines.push(`| ${plan.name} | ${plan.protocol} | ${plan.blockedAt} | ${exit} | ${plan.openable ? "○" : "×"} | ${plan.todos.length} 件 |`);
  }
  return lines.join("\n");
}
