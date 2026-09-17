// 問題6（発展）: 提携先 3 社の受け入れ計画を、事実から機械的に導く。
// 「方式・プロビジョニング・アカウントの結び付け・ログアウト・残るリスク」を 1 つの表にします。
import { chooseProtocol } from "./bookstore-saml-oidc.js";
import type { FederationProtocol, FederationRequirement } from "./bookstore-saml-oidc.js";
import { delayedEvents, uncoveredEvents } from "./rp-lifecycle-sync.js";
import type { ProvisionMode } from "./rp-lifecycle-sync.js";

/** 相手について集めた事実。ここに希望や好みを混ぜないこと */
export type PartnerInput = {
  readonly name: string;
  readonly requirement: FederationRequirement;
  /** 相手が利用者の名簿を押し込める口（SCIM）を持っているか */
  readonly hasScimApi: boolean;
  /** グループ（部門・職種）を送ってくるか */
  readonly sendsGroups: boolean;
  /** 書店側の既存アカウントと同じメールドメインを使っているか */
  readonly sharedEmailDomain: boolean;
  /** 受け入れる人数（残ったアカウントがそのまま費用になります） */
  readonly seats: number;
};

export type LinkingPolicy = "auto-by-key" | "manual-review";
export type LogoutPlan = "oidc-backchannel" | "saml-slo" | "none";

export type PartnerPlan = {
  readonly name: string;
  readonly protocol: FederationProtocol | "none";
  readonly protocolReason: string;
  readonly provisioning: ProvisionMode;
  readonly linking: LinkingPolicy;
  readonly logout: LogoutPlan;
  readonly risks: readonly string[];
};

const logoutFor = (protocol: FederationProtocol | "none"): LogoutPlan =>
  protocol === "oidc" ? "oidc-backchannel" : protocol === "saml2" ? "saml-slo" : "none";

export function planFor(input: PartnerInput): PartnerPlan {
  const choice = chooseProtocol(input.requirement);
  const provisioning: ProvisionMode = input.hasScimApi ? "jit+scim" : "jit-only";
  const linking: LinkingPolicy = input.sharedEmailDomain ? "manual-review" : "auto-by-key";
  const risks: string[] = [];

  if (choice.protocol === "none") {
    risks.push("連携できない。相手に IdP を用意してもらうまで着手しない");
  }
  if (choice.protocol === "saml2" && input.requirement.needsApiToken) {
    risks.push("SAML では API のアクセストークンが出ない。API 用の認可を別に用意する");
  }
  for (const event of uncoveredEvents(provisioning)) {
    risks.push(`${event} が自動で反映されない（${input.seats} 席分の棚卸しを定期作業にする）`);
  }
  if (delayedEvents(provisioning).includes("group-change")) {
    risks.push("権限の剥奪が次のログインまで効かない");
  }
  if (!input.sendsGroups) {
    risks.push("グループが送られてこない。権限は書店側で付ける（ロールの写し取りは行わない）");
  }
  if (input.sharedEmailDomain) {
    risks.push("メールアドレスが重なる。自動リンクを禁止し、本人確認の手順を用意する");
  }

  return {
    name: input.name,
    protocol: choice.protocol,
    protocolReason: choice.reason,
    provisioning,
    linking,
    logout: logoutFor(choice.protocol),
    risks,
  };
}

/** 3 つの提携先。数値と真偽だけを書き、判断は planFor に任せます */
export const PARTNER_INPUTS: readonly PartnerInput[] = [
  {
    name: "大手チェーン",
    requirement: { partnerSupports: ["saml2"], hasNativeApp: false, needsApiToken: true, partnerPolicy: "saml2" },
    hasScimApi: true,
    sendsGroups: true,
    sharedEmailDomain: false,
    seats: 200,
  },
  {
    name: "小規模書店",
    requirement: { partnerSupports: ["saml2", "oidc"], hasNativeApp: true, needsApiToken: true, partnerPolicy: "none" },
    hasScimApi: false,
    sendsGroups: true,
    sharedEmailDomain: true,
    seats: 12,
  },
  {
    name: "個人経営の書店",
    requirement: { partnerSupports: [], hasNativeApp: false, needsApiToken: false, partnerPolicy: "none" },
    hasScimApi: false,
    sendsGroups: false,
    sharedEmailDomain: false,
    seats: 1,
  },
];

export const planAll = (inputs: readonly PartnerInput[] = PARTNER_INPUTS): readonly PartnerPlan[] =>
  inputs.map(planFor);

export function planTable(inputs: readonly PartnerInput[] = PARTNER_INPUTS): string {
  const lines = [
    "| 提携先 | 方式 | プロビジョニング | 結び付け | ログアウト | 残るリスク |",
    "| :--- | :--- | :--- | :--- | :--- | :--- |",
  ];
  for (const plan of planAll(inputs)) {
    lines.push(
      `| ${plan.name} | ${plan.protocol} | ${plan.provisioning} | ${plan.linking} | ${plan.logout} | ${plan.risks.length} 件 |`,
    );
  }
  return lines.join("\n");
}
