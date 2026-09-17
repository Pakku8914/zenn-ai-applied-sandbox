// 外部 IdP が名乗るクレームを、書店側のプロフィールに写し取ります（属性マッピング）。
// 要点は 2 つ。必須の属性が埋まらない写し方は失敗として扱うこと。
// そして、相手が名乗った権限をそのまま受け取らないこと（許可リストにある組だけ通す）。

export type MappingTarget = "username" | "email" | "displayName" | "storeId" | "roles";
export type MappingSource = "claim" | "constant" | "group-to-role";
/** 2 回目以降のログインで上書きするか、初回に決めた値を守るか */
export type UpdatePolicy = "overwrite" | "first-login-only";

export type MappingRule = {
  readonly target: MappingTarget;
  readonly source: MappingSource;
  /** claim なら外部のクレーム名、constant なら値そのもの、group-to-role ならグループが入るクレーム名 */
  readonly from: string;
  readonly required: boolean;
  readonly onUpdate: UpdatePolicy;
};

/** partner realm から来た利用者を、書店のプロフィールに写す定義 */
export const PARTNER_MAPPING: readonly MappingRule[] = [
  { target: "username", source: "claim", from: "preferred_username", required: true, onUpdate: "first-login-only" },
  { target: "email", source: "claim", from: "email", required: true, onUpdate: "overwrite" },
  { target: "displayName", source: "claim", from: "name", required: false, onUpdate: "overwrite" },
  // 担当店舗はこちらで決めます。相手が名乗った店舗を信じてはいけません
  { target: "storeId", source: "constant", from: "ueno", required: true, onUpdate: "first-login-only" },
  { target: "roles", source: "group-to-role", from: "groups", required: false, onUpdate: "overwrite" },
];

/** 外部のグループ名 → 書店の realm ロール。この表に無い名前は捨てます（許可リスト） */
export const GROUP_TO_ROLE: Readonly<Record<string, string>> = {
  "partner-staff": "staff",
  "partner-members": "customer",
};

export type ExternalClaims = Readonly<Record<string, unknown>>;

export type ShopProfile = {
  readonly username: string;
  readonly email: string;
  readonly displayName: string;
  readonly storeId: string;
  readonly roles: readonly string[];
};

export type MappingResult =
  | { readonly ok: true; readonly profile: ShopProfile; readonly dropped: readonly string[] }
  | { readonly ok: false; readonly missing: readonly MappingTarget[]; readonly dropped: readonly string[] };

const asString = (value: unknown): string => (typeof value === "string" ? value : "");
const asStringArray = (value: unknown): readonly string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

/** 必須の属性が 1 つでも埋まらなければ ok: false を返し、足りない属性を名前で伝えます */
export function mapClaims(claims: ExternalClaims, rules: readonly MappingRule[] = PARTNER_MAPPING): MappingResult {
  const text = new Map<MappingTarget, string>();
  const roles: string[] = [];
  const dropped: string[] = [];
  const missing: MappingTarget[] = [];

  for (const rule of rules) {
    if (rule.target === "roles") {
      for (const group of asStringArray(claims[rule.from])) {
        const role = GROUP_TO_ROLE[group];
        if (role === undefined) {
          dropped.push(group); // 知らないグループ名は捨て、捨てた事実だけ残します
        } else if (!roles.includes(role)) {
          roles.push(role);
        }
      }
      if (rule.required && roles.length === 0) {
        missing.push("roles");
      }
      continue;
    }
    const value = rule.source === "constant" ? rule.from : asString(claims[rule.from]);
    if (value === "") {
      if (rule.required) {
        missing.push(rule.target);
      }
      continue;
    }
    text.set(rule.target, value);
  }

  const profile: ShopProfile = {
    username: text.get("username") ?? "",
    email: text.get("email") ?? "",
    displayName: text.get("displayName") ?? "",
    storeId: text.get("storeId") ?? "",
    roles,
  };
  return missing.length > 0 ? { ok: false, missing, dropped } : { ok: true, profile, dropped };
}

type MutableProfile = {
  username: string;
  email: string;
  displayName: string;
  storeId: string;
  roles: readonly string[];
};

/**
 * 2 回目以降のログインで、プロフィールをどこまで上書きするかを決めます。
 * 全部を毎回上書きすると書店側で直した値が巻き戻り、何も上書きしないと改姓や異動が永遠に届きません。
 */
export function applyUpdate(
  stored: ShopProfile,
  incoming: ShopProfile,
  rules: readonly MappingRule[] = PARTNER_MAPPING,
): { readonly profile: ShopProfile; readonly changed: readonly MappingTarget[] } {
  const overwritable = new Set(rules.filter((rule) => rule.onUpdate === "overwrite").map((rule) => rule.target));
  const next: MutableProfile = { ...stored };
  const changed: MappingTarget[] = [];

  for (const target of ["username", "email", "displayName", "storeId"] as const) {
    const after = incoming[target];
    if (!overwritable.has(target) || after === "" || after === stored[target]) {
      continue;
    }
    next[target] = after;
    changed.push(target);
  }
  if (overwritable.has("roles") && JSON.stringify(stored.roles) !== JSON.stringify(incoming.roles)) {
    next.roles = incoming.roles;
    changed.push("roles");
  }
  return { profile: next, changed };
}
