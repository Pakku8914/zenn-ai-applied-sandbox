// 問題3（セッション15 後半）: 連携鍵をメールアドレスにすると何が壊れるかを、2 つの引き方で並べて再現する。
import { FederatedUserStore } from "./rp-jit-provisioning.js";
import type { FederatedKey, ProvisionResult, ShopUser } from "./rp-jit-provisioning.js";
import type { ShopProfile } from "./rp-attribute-mapping.js";

export const PARTNER_ISSUER = "http://keycloak:8080/realms/partner";
const OTHER_ISSUER = "https://idp.another-partner.example";
const STORED_EMAIL = "carol@partner.example";

// subjectKey が本来の引き方。emailKey は「メールアドレスを識別子にする」壊れた引き方です
export const subjectKey = (issuer: string, subject: string): FederatedKey => ({ issuer, subject });
export const emailKey = (email: string): FederatedKey => ({ issuer: "email", subject: email });

const profileOf = (username: string, email: string): ShopProfile => ({ username, email, displayName: username, storeId: "ueno", roles: ["staff"] });

/** 場面と、そこで新しく来るログイン。rename だけ subject が既存と同じ（同じ人）です */
export const CASES = [
  { scenario: "rename", issuer: PARTNER_ISSUER, subject: "carol-subject", email: "carol.ueno@partner.example", name: "carol" },
  { scenario: "handover", issuer: PARTNER_ISSUER, subject: "dave-subject", email: STORED_EMAIL, name: "dave" },
  { scenario: "cross-idp", issuer: OTHER_ISSUER, subject: "carol-subject", email: STORED_EMAIL, name: "carol" },
] as const;

export type Scenario = (typeof CASES)[number]["scenario"];

const outcomeLabel = (result: ProvisionResult): string =>
  result.outcome === "rejected" ? `rejected / ${result.reason}` : `${result.outcome} / ${result.user.userId}`;

export type Comparison = {
  readonly scenario: Scenario;
  readonly byEmail: string;
  readonly bySubject: string;
  /** メールアドレスで引くと事故になるか */
  readonly brokenByEmail: boolean;
};

/** 既存の 1 件だけを持つストアを毎回作り直します（前の場面の結果を持ち越さないため） */
const storeWith = (key: FederatedKey): FederatedUserStore => {
  const seed: ShopUser = { userId: "shop-1", key, profile: profileOf("carol", STORED_EMAIL), active: true, createdBy: "jit" };
  return new FederatedUserStore([seed]);
};

/** 同じ場面を 2 つの引き方で通します。引き方だけで結果が変わることを見ます */
export const compareAll = (): readonly Comparison[] =>
  CASES.map((entry) => {
    const profile = profileOf(entry.name, entry.email);
    const byEmail = outcomeLabel(storeWith(emailKey(STORED_EMAIL)).provision(emailKey(entry.email), profile));
    const bySubject = outcomeLabel(
      storeWith(subjectKey(PARTNER_ISSUER, "carol-subject")).provision(subjectKey(entry.issuer, entry.subject), profile),
    );
    // 改姓は「分かれてしまう」ことが事故、引き継ぎと名乗りは「つながってしまう」ことが事故です
    const brokenByEmail = byEmail.startsWith(entry.scenario === "rename" ? "created" : "reused");
    return { scenario: entry.scenario, byEmail, bySubject, brokenByEmail };
  });
