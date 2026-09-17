// セッション 15 の共通モジュール。「信頼関係」の実体を型と判定で表します。
// 題材は realm を 2 つ使う構成です（bookstore = 書店の realm、partner = 提携先の IdP に見立てた realm）。

/** 信頼関係を成り立たせる 4 つの材料。1 つでも欠けると連携は設定できません */
export type TrustMaterial = "issuer-id" | "signing-key" | "endpoints" | "client-registration";

export type TrustMaterialDoc = {
  readonly kind: TrustMaterial;
  readonly label: string;
  /** OIDC での採りどころ */
  readonly oidc: string;
  /** SAML での採りどころ */
  readonly saml: string;
};

export const TRUST_MATERIALS: readonly TrustMaterialDoc[] = [
  { kind: "issuer-id", label: "相手を一意に指す名前", oidc: "discovery の issuer", saml: "メタデータの entityID" },
  { kind: "signing-key", label: "署名を検証する公開鍵", oidc: "jwks_uri（鍵そのものではなく入手口）", saml: "メタデータの KeyDescriptor（証明書を貼る）" },
  { kind: "endpoints", label: "どこへ送り、どこで受けるか", oidc: "authorization_endpoint / token_endpoint", saml: "SingleSignOnService / AssertionConsumerService" },
  { kind: "client-registration", label: "相手側に登録された自分の名前", oidc: "client_id と redirect_uri", saml: "SP の entityID と ACS URL" },
];

export type TrustCheck = {
  readonly kind: TrustMaterial;
  readonly satisfied: boolean;
  /** どこから採れたか（採れなかったときは、どこを見ればよいか） */
  readonly source: string;
};

const isNonEmptyString = (value: unknown): boolean => typeof value === "string" && value.length > 0;

/**
 * discovery 文書とクライアント登録から、信頼関係の材料がそろっているかを判定します。
 * 「IdP を登録する設定に何を書き写すのか」を、そのまま判定の形にしたものです。
 */
export function checkTrust(
  config: Readonly<Record<string, unknown>>,
  registeredClientId: string | undefined,
): readonly TrustCheck[] {
  return [
    { kind: "issuer-id", satisfied: isNonEmptyString(config["issuer"]), source: "issuer" },
    { kind: "signing-key", satisfied: isNonEmptyString(config["jwks_uri"]), source: "jwks_uri" },
    {
      kind: "endpoints",
      satisfied: isNonEmptyString(config["authorization_endpoint"]) && isNonEmptyString(config["token_endpoint"]),
      source: "authorization_endpoint / token_endpoint",
    },
    {
      // discovery には出てきません。相手の realm に自分を登録してもらう作業が必要です
      kind: "client-registration",
      satisfied: registeredClientId !== undefined && registeredClientId.length > 0,
      source: "相手の realm に登録したクライアント（discovery には出てこない）",
    },
  ];
}

/** 欠けている材料。空配列なら、連携の設定に必要な情報はそろっています */
export const missingTrust = (checks: readonly TrustCheck[]): readonly TrustMaterial[] =>
  checks.filter((check) => !check.satisfied).map((check) => check.kind);
