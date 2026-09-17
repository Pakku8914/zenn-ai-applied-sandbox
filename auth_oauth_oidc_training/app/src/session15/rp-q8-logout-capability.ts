// 問題4（セッション15 前半）: discovery から「出口」の対応状況を判定する。
// 連携すると入口だけでなく出口（ログアウト）が増えます。対応状況は discovery が申告しています。
// 落とし穴: backchannel_ で始まる申告は 2 系統あり、片方はログアウトと無関係です。

/** ログアウトの 3 方式 */
export const LOGOUT_STYLES = ["rp-initiated", "front-channel", "back-channel"] as const;
export type LogoutStyle = (typeof LOGOUT_STYLES)[number];

export type StyleSpec = {
  readonly style: LogoutStyle;
  readonly label: string;
  /** 対応していると言えるために値が入っていなければならない申告 */
  readonly requires: readonly string[];
  /** 申告の型。エンドポイントは文字列、能力の申告は真偽値 */
  readonly valueKind: "string" | "boolean";
  /** どの利用者のセッションを閉じるかを伝えられるか（申告が無い方式は null） */
  readonly sessionField: string | null;
};

export const LOGOUT_SPECS: readonly StyleSpec[] = [
  { style: "rp-initiated", label: "RP 起動ログアウト", requires: ["end_session_endpoint"], valueKind: "string", sessionField: null },
  { style: "front-channel", label: "フロントチャネルログアウト", requires: ["frontchannel_logout_supported"], valueKind: "boolean", sessionField: "frontchannel_logout_session_supported" },
  { style: "back-channel", label: "バックチャネルログアウト", requires: ["backchannel_logout_supported"], valueKind: "boolean", sessionField: "backchannel_logout_session_supported" },
];

/** 名前が似ているだけの申告。CIBA（別端末での認証）のもので、ログアウトの根拠になりません */
export const CIBA_FIELDS: readonly string[] = ["backchannel_authentication_endpoint", "backchannel_token_delivery_modes_supported"];

const hasText = (value: unknown): boolean => typeof value === "string" && value.length > 0;
const isTrue = (value: unknown): boolean => value === true;

export type LogoutSupport = {
  readonly style: LogoutStyle;
  readonly label: string;
  readonly supported: boolean;
  /** 判定に使った申告。真偽値だけを返さず、根拠も残します */
  readonly evidence: readonly string[];
  readonly sessionAware: boolean;
};

function specOf(style: LogoutStyle): StyleSpec {
  const found = LOGOUT_SPECS.find((spec) => spec.style === style);
  if (found === undefined) {
    throw new Error(`未知のログアウト方式です: ${style}`);
  }
  return found;
}

/** 1 方式の判定。requires がすべて埋まっているときだけ true です */
export function supportsLogout(config: Readonly<Record<string, unknown>>, style: LogoutStyle): boolean {
  const spec = specOf(style);
  const ok = spec.valueKind === "string" ? hasText : isTrue;
  return spec.requires.every((field) => ok(config[field]));
}

export const logoutSupport = (config: Readonly<Record<string, unknown>>): readonly LogoutSupport[] =>
  LOGOUT_SPECS.map((spec) => ({
    style: spec.style,
    label: spec.label,
    supported: supportsLogout(config, spec.style),
    evidence: spec.requires,
    sessionAware: spec.sessionField !== null && isTrue(config[spec.sessionField]),
  }));

/** 使える方式。「どこまで閉じられるか」を決める材料になります */
export const supportedStyles = (config: Readonly<Record<string, unknown>>): readonly LogoutStyle[] =>
  logoutSupport(config)
    .filter((row) => row.supported)
    .map((row) => row.style);

/** 取り違えやすい申告。「backchannel と書いてあるから対応している」が典型的な誤りです */
export const misreadRisks = (config: Readonly<Record<string, unknown>>): readonly string[] =>
  CIBA_FIELDS.filter((field) => config[field] !== undefined).map(
    (field) => `${field} は CIBA の申告。バックチャネルログアウトの根拠にしない`,
  );

export function logoutReport(config: Readonly<Record<string, unknown>>): string {
  const lines = ["| 方式 | 対応 | セッション指定 | 判定に使った申告 |", "| :--- | :--- | :--- | :--- |"];
  for (const row of logoutSupport(config)) {
    lines.push(`| ${row.label} | ${row.supported ? "○" : "×"} | ${row.sessionAware ? "○" : "―"} | ${row.evidence.join(" / ")} |`);
  }
  return lines.join("\n");
}
