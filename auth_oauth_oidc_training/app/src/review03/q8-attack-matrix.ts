// 横断復習③ 問題 8: 観測した防御の状態を「どの攻撃が成立するか」の表に翻訳します。
// コールバック・リダイレクト照合・API から測れる 5 項目は問題文で与えられた値を使い、
// 認可リクエストにしか現れない PKCE だけを自分で測ります。
// 根拠にするのは観測値だけで、構成の名前や設定表は 1 度も見ません。

export type ObservedDefenses = {
  /** 対照。正しいコールバックを受理できたか。false なら残りの観測は当てにできません */
  readonly acceptsOwnCallback: boolean;
  readonly verifiesState: boolean;
  readonly verifiesIssuer: boolean;
  readonly exactRedirect: boolean;
  readonly verifiesAudience: boolean;
  readonly pkceS256: boolean;
};

/** 問題文で与えられる 5 項目。pkceS256 だけは自分で測ります */
export type GivenObservations = Omit<ObservedDefenses, "pkceS256">;

/** PKCE はコールバックからは測れません。認可リクエストの URL に載っているかを見ます */
export function observePkceS256(authorizationUrl: string): boolean {
  const params = new URL(authorizationUrl).searchParams;
  // plain は割符のハッシュではなく現物をブラウザに通すので、守りとして数えません
  return params.get("code_challenge_method") === "S256" && (params.get("code_challenge") ?? "") !== "";
}

// ── 観測値 → 攻撃の成立表 ────────────────────────────────────────────────

export type AttackName = "認可コード横取り" | "ログイン CSRF" | "混乱した代理" | "トークン置換";

export type AttackRow = {
  readonly attack: AttackName;
  /** 成立するか。守りの層が 1 つでも生きていれば false */
  readonly succeeds: boolean;
  /** 成立を止めた防御。succeeds が true なら空配列 */
  readonly stoppedBy: readonly string[];
};

/** 防御は層として重ねるので、1 つでも生きていれば攻撃は成立しません（多層防御） */
function row(attack: AttackName, layers: readonly [string, boolean][]): AttackRow {
  const stoppedBy = layers.filter(([, alive]) => alive).map(([name]) => name);
  return { attack, succeeds: stoppedBy.length === 0, stoppedBy };
}

export function attackMatrix(o: ObservedDefenses): readonly AttackRow[] {
  return [
    // 宛先を絞れなければコードが攻撃者に渡り、PKCE(S256) が無ければ交換までできる（層が 2 枚）
    row("認可コード横取り", [["redirect_uri 完全一致", o.exactRedirect], ["PKCE(S256)", o.pkceS256]]),
    row("ログイン CSRF", [["state の照合", o.verifiesState]]),
    row("混乱した代理", [["iss の照合", o.verifiesIssuer]]),
    row("トークン置換", [["aud の検証", o.verifiesAudience]]),
  ];
}

export const succeedingAttacks = (matrix: readonly AttackRow[]): readonly AttackName[] =>
  matrix.filter((entry) => entry.succeeds).map((entry) => entry.attack);
