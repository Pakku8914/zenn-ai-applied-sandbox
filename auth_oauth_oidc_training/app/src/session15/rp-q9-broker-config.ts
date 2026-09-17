// 問題5（セッション15 前半）: Identity Brokering の登録内容を、realm に触らずに組み立てて検証する。
// realm を作る前に「何を書くことになるか」を確定させ、値の誤りはここで全部落とし切ります。
import { checkTrust, missingTrust } from "./bookstore-sso-actors.js";
import type { TrustMaterial } from "./bookstore-sso-actors.js";

/** 相手の realm に自分（書店の Keycloak）を登録したときに決まる値 */
export type BrokerInput = {
  readonly localRealm: string;
  readonly keycloakBase: string;
  /** こちらが付ける IdP の別名。受け口の URL に現れるので外から見えます */
  readonly alias: string;
  readonly partnerDiscovery: Readonly<Record<string, unknown>>;
  /** 相手に発行してもらったクライアント ID。まだなら undefined */
  readonly clientId: string | undefined;
  /** クライアント秘密の「置き場所」。秘密そのものは設定に書きません */
  readonly clientSecretRef: string;
  readonly scopes: readonly string[];
};

export type BrokerConfig = {
  readonly alias: string;
  readonly providerId: "oidc";
  readonly enabled: true;
  /** 相手が「確認済み」と言ってもこちらでは確認済みにしない（自動リンクの事故を防ぐ） */
  readonly trustEmail: false;
  readonly redirectUri: string;
  readonly config: {
    readonly clientId: string;
    readonly clientSecretRef: string;
    readonly clientAuthMethod: "client_secret_post";
    readonly authorizationUrl: string;
    readonly tokenUrl: string;
    readonly jwksUrl: string;
    readonly useJwksUrl: "true";
    readonly defaultScope: string;
    readonly syncMode: "FORCE";
  };
};

export type BuildResult =
  | { readonly ok: true; readonly value: BrokerConfig }
  | { readonly ok: false; readonly missing: readonly TrustMaterial[]; readonly problems: readonly string[] };

/** ブローカーの受け口。Keycloak はこの URL で外部 IdP からの応答を受けます */
export const brokerRedirectUri = (keycloakBase: string, localRealm: string, alias: string): string =>
  `${keycloakBase}/realms/${localRealm}/broker/${alias}/endpoint`;

/** 別名は URL に現れるので、英小文字・数字・ハイフンだけに限ります */
const ALIAS_PATTERN = /^[a-z][a-z0-9-]*$/;
/** 秘密の置き場所は環境変数名で受け取ります（値が直接入っていたら気づけるように） */
const SECRET_REF_PATTERN = /^[A-Z][A-Z0-9_]*$/;

const asText = (value: unknown): string => (typeof value === "string" ? value : "");

/** 値がそろっていても設計として危ないものを拾います */
export function reviewInput(input: BrokerInput): readonly string[] {
  const problems: string[] = [];
  if (!ALIAS_PATTERN.test(input.alias)) {
    problems.push(`alias が URL に使えない形です: ${JSON.stringify(input.alias)}`);
  }
  if (!SECRET_REF_PATTERN.test(input.clientSecretRef)) {
    problems.push("clientSecretRef が環境変数名の形ではありません（秘密そのものを渡していませんか）");
  }
  if (!input.scopes.includes("openid")) {
    problems.push("scopes に openid がありません（OIDC として扱われず ID トークンが返りません）");
  }
  if (!input.scopes.includes("email")) {
    problems.push("scopes に email がありません（属性マッピングで email が埋まりません）");
  }
  return problems;
}

/**
 * 4 材料がそろい、指摘が 1 件も無いときだけ設定を返します。
 * 「とりあえず作って、あとで直す」を許すと、直し忘れた設定が本番に残ります。
 */
export function buildBrokerConfig(input: BrokerInput): BuildResult {
  const missing = missingTrust(checkTrust(input.partnerDiscovery, input.clientId));
  const problems = reviewInput(input);
  if (missing.length > 0 || problems.length > 0) {
    return { ok: false, missing, problems };
  }
  return {
    ok: true,
    value: {
      alias: input.alias,
      providerId: "oidc",
      enabled: true,
      trustEmail: false,
      redirectUri: brokerRedirectUri(input.keycloakBase, input.localRealm, input.alias),
      config: {
        // missing が空なので clientId は必ず入っています（checkTrust がそれを見ています）
        clientId: input.clientId ?? "",
        clientSecretRef: input.clientSecretRef,
        clientAuthMethod: "client_secret_post",
        authorizationUrl: asText(input.partnerDiscovery["authorization_endpoint"]),
        tokenUrl: asText(input.partnerDiscovery["token_endpoint"]),
        jwksUrl: asText(input.partnerDiscovery["jwks_uri"]),
        useJwksUrl: "true",
        defaultScope: [...input.scopes].join(" "),
        syncMode: "FORCE",
      },
    },
  };
}

const PARTNER = "http://keycloak:8080/realms/partner";

/** 検証用の「相手の discovery」。partner realm を作らずに組み立てを確かめる見立てです */
export const SAMPLE_PARTNER_DISCOVERY: Readonly<Record<string, unknown>> = {
  issuer: PARTNER,
  authorization_endpoint: `${PARTNER}/protocol/openid-connect/auth`,
  token_endpoint: `${PARTNER}/protocol/openid-connect/token`,
  jwks_uri: `${PARTNER}/protocol/openid-connect/certs`,
};

/** 正しくそろった入力の例 */
export const SAMPLE_INPUT: BrokerInput = {
  localRealm: "bookstore",
  keycloakBase: "http://keycloak:8080",
  alias: "partner",
  partnerDiscovery: SAMPLE_PARTNER_DISCOVERY,
  clientId: "bookstore-broker",
  clientSecretRef: "PARTNER_BROKER_SECRET",
  scopes: ["openid", "profile", "email"],
};
