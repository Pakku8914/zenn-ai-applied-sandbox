// 問題 3 の解答: 配置形態ごとの方針を、realm に書く設定まで落とします。
// 「ローテーションが必須」で終わらせず、どの項目をどう変えるかまで決めるのが目的です。
import { ALL_PLACEMENTS, ROTATION_SETTINGS, refreshPolicyFor } from "./public-client-refresh.js";
import type { Placement } from "./public-client-refresh.js";

/** 本書の realm-bookstore.json の既定値（セッション 7 の実測値） */
export const REALM_DEFAULTS = {
  revokeRefreshToken: false,
  refreshTokenMaxReuse: 0,
  ssoSessionIdleTimeout: 1800,
} as const;

export type RealmRefreshSettings = {
  readonly revokeRefreshToken: boolean;
  readonly refreshTokenMaxReuse: number;
  /** アイドル期限（秒）。短いほど、盗まれたトークンが使える窓が狭くなる */
  readonly ssoSessionIdleTimeout: number;
  readonly reason: string;
};

/**
 * 配置形態から realm の設定を導きます。
 * ローテーションが要らない配置では既定のまま（＝理由なく設定を増やさない）にします。
 */
export function settingsFor(placement: Placement): RealmRefreshSettings {
  const policy = refreshPolicyFor(placement);
  if (!policy.rotationRequired) {
    return {
      ...REALM_DEFAULTS,
      reason: "クライアント認証で呼び出し元を確かめられるので、既定のままでよい",
    };
  }
  return {
    revokeRefreshToken: ROTATION_SETTINGS.revokeRefreshToken,
    refreshTokenMaxReuse: ROTATION_SETTINGS.refreshTokenMaxReuse,
    // 端末側に置くなら窓も狭める。ここは設計上の選択で、既定値の半分にした例です
    ssoSessionIdleTimeout: policy.tokenOnClient
      ? REALM_DEFAULTS.ssoSessionIdleTimeout / 2
      : REALM_DEFAULTS.ssoSessionIdleTimeout,
    reason: "クライアント認証ができないので、1 回しか使えない形にして再利用を検知する",
  };
}

/** ローテーションだけでは足りない理由を、起きる順番で並べます */
export const WHY_DETECTION_IS_NEEDED: readonly string[] = [
  "攻撃者がリフレッシュトークン R1 を盗む（利用者はまだ R1 を持っている）",
  "攻撃者が先に R1 を使う。ローテーションにより R1 は無効になり、攻撃者が R2 を得る",
  "利用者が R1 を使おうとして失敗する。ここで「誰かに使われた」ことが分かる",
  "再利用を検知したらセッションごと落とす。落とさなければ、攻撃者の R2 は生き続ける",
];

export type PolicyRow = {
  readonly placement: Placement;
  readonly label: string;
  readonly rotationRequired: boolean;
  readonly settings: RealmRefreshSettings;
};

export function policyRows(placements: readonly Placement[] = ALL_PLACEMENTS): readonly PolicyRow[] {
  return placements.map((placement) => {
    const policy = refreshPolicyFor(placement);
    return {
      placement,
      label: policy.label,
      rotationRequired: policy.rotationRequired,
      settings: settingsFor(placement),
    };
  });
}

export function toMarkdown(rows: readonly PolicyRow[] = policyRows()): string {
  const header = "| 配置形態 | revokeRefreshToken | refreshTokenMaxReuse | ssoSessionIdleTimeout | 理由 |";
  const rule = "| :--- | :--- | :--- | :--- | :--- |";
  const body = rows.map(
    (row) =>
      `| ${row.label} | ${row.settings.revokeRefreshToken} | ${row.settings.refreshTokenMaxReuse} | ${row.settings.ssoSessionIdleTimeout} | ${row.settings.reason} |`,
  );
  return [header, rule, ...body].join("\n");
}
