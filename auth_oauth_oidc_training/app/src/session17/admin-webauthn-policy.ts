// セッション 17: Keycloak 側に「WebAuthn の口」が用意されていることを読み取るだけのコード。
// GET しか投げません（realm は 1 か所も書き換えません）。
// 読み取った値を本文で断定しないのは、realm-bookstore.json に書いていない＝ Keycloak の既定値であり、
// バージョンで変わりうるからです。自分の環境の値は verify.ts の出力で確かめてください。
import { REALM, adminFetch } from "../session16/bookstore-keys.js";

const asRecord = (value: unknown): Record<string, unknown> =>
  (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
const asString = (value: unknown): string => (typeof value === "string" ? value : "");
const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

export type WebAuthnPolicyView = {
  /** 2 要素目として使う設定のキー（webAuthnPolicy*） */
  readonly twoFactorKeys: readonly string[];
  /** パスワードレスとして使う設定のキー（webAuthnPolicyPasswordless*） */
  readonly passwordlessKeys: readonly string[];
  /** 読み取った値（キー → JSON 文字列） */
  readonly values: Readonly<Record<string, string>>;
};

/** realm の表現から webAuthnPolicy で始まる設定だけを抜き出します */
export async function fetchWebAuthnPolicy(token: string): Promise<WebAuthnPolicyView> {
  const res = await adminFetch(token, `/realms/${REALM}`);
  if (!res.ok) throw new Error(`realm の設定の取得に失敗しました: HTTP ${res.status}`);
  const realm = asRecord(await res.json());
  const keys = Object.keys(realm)
    .filter((key) => key.startsWith("webAuthnPolicy"))
    .sort();
  return {
    twoFactorKeys: keys.filter((key) => !key.startsWith("webAuthnPolicyPasswordless")),
    passwordlessKeys: keys.filter((key) => key.startsWith("webAuthnPolicyPasswordless")),
    values: Object.fromEntries(keys.map((key) => [key, JSON.stringify(realm[key])])),
  };
}

/** 利用者に「登録してください」と促す口（required action）のうち、WebAuthn 用のもの */
export type RequiredActionView = {
  readonly alias: string;
  readonly registered: boolean;
  readonly enabled: boolean;
};

async function readActions(token: string, path: string, registered: boolean): Promise<RequiredActionView[]> {
  const res = await adminFetch(token, path);
  // 版によって無いことがある口なので、読めなければ「無かった」として扱います
  if (!res.ok) return [];
  return asArray(await res.json()).map((item) => {
    const record = asRecord(item);
    return {
      alias: asString(record["alias"]) || asString(record["providerId"]),
      registered,
      enabled: record["enabled"] === true,
    };
  });
}

export async function fetchWebAuthnRequiredActions(token: string): Promise<RequiredActionView[]> {
  const registered = await readActions(token, `/realms/${REALM}/authentication/required-actions`, true);
  const unregistered = await readActions(token, `/realms/${REALM}/authentication/unregistered-required-actions`, false);
  return [...registered, ...unregistered]
    .filter((action) => action.alias.toLowerCase().includes("webauthn"))
    .sort((a, b) => a.alias.localeCompare(b.alias));
}

/** ブラウザのログインフローに差し込める認証の部品のうち、WebAuthn 用のもの */
export async function fetchWebAuthnAuthenticators(token: string): Promise<string[]> {
  const res = await adminFetch(token, `/realms/${REALM}/authentication/authenticator-providers`);
  if (!res.ok) return [];
  return asArray(await res.json())
    .map((item) => asString(asRecord(item)["id"]))
    .filter((id) => id.toLowerCase().includes("webauthn"))
    .sort();
}
