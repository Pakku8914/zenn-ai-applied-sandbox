// 練習問題 6: ログインの防御を「設定表として書かれているか」と「実装として動いているか」の
// 2 通りで測り、その食い違いを洗い出す総合監査。
// 設定表の点検（auditLoginDefenses）だけでは「設定はあるのに動いていない」を見逃します。
import type { Hono } from "hono";
import type { ApiEnv } from "../session10/api-service-claims.js";
import { hijackableUris } from "./rp-q1-redirect-allowlist.js";

export type RedirectMatching = "exact" | "wildcard" | "none";

export type LoginConfig = {
  /** 認可リクエストの code_challenge_method（"S256" | "plain" | null） */
  readonly codeChallengeMethod: "S256" | "plain" | null;
  /** コールバックで state を照合するか */
  readonly verifiesState: boolean;
  /** コールバックで iss を照合するか（RFC 9207） */
  readonly verifiesIssuer: boolean;
  /** リダイレクト URI の照合方式 */
  readonly redirectMatching: RedirectMatching;
  /** リソースサーバーが aud を検証するか */
  readonly verifiesAudience: boolean;
};

export type DefenseCheck = { readonly name: string; readonly ok: boolean; readonly note: string };

export type DefenseReport = {
  readonly checks: DefenseCheck[];
  readonly missing: string[];
  readonly secure: boolean;
};

/** 設定表を 5 つの防御に照らし、欠けているものを洗い出します（設定からの点検） */
export function auditLoginDefenses(config: LoginConfig): DefenseReport {
  const checks: DefenseCheck[] = [
    {
      name: "PKCE(S256)",
      ok: config.codeChallengeMethod === "S256",
      note: "認可コードを横取りされても、code_verifier が無ければ交換できない",
    },
    {
      name: "state",
      ok: config.verifiesState,
      note: "自分が始めたログインかを確かめ、ログインの取り違え（CSRF）を防ぐ",
    },
    {
      name: "iss",
      ok: config.verifiesIssuer,
      note: "どの認可サーバーからの応答かを確かめ、混乱した代理を防ぐ",
    },
    {
      name: "redirect_uri 完全一致",
      ok: config.redirectMatching === "exact",
      note: "登録済みの正確な宛先にだけコードを返し、オープンリダイレクトの足がかりを消す",
    },
    {
      name: "aud",
      ok: config.verifiesAudience,
      note: "自分宛てのトークンかを確かめ、トークン置換を防ぐ",
    },
  ];
  const missing = checks.filter((check) => !check.ok).map((check) => check.name);
  return { checks, missing, secure: missing.length === 0 };
}

// ── ここから「挙動からの点検」────────────────────────────────────────────

/** プローブに使える受け口。ログインを始める start は求めず、remember と consume だけを求めます */
export type ProbeableStore = {
  remember(entry: { state: string; codeVerifier: string; expectedIssuer: string }): void;
  consume(params: URLSearchParams): { code: string };
};

export type ObservationTargets = {
  /** プローブごとに新しい受け口を作る関数。前のプローブの使い捨て記録に影響されないようにします */
  readonly makeStore: () => ProbeableStore;
  /** ログインを始めた相手。プローブのコールバックに載せる iss */
  readonly expectedIssuer: string;
  /** リダイレクト URI の照合関数。完全一致・ワイルドカード・何もしない、のどれが渡るかは分かりません */
  readonly matchesRedirect: (uri: string) => boolean;
  /** aud を検証しているか調べる相手 */
  readonly api: Hono<ApiEnv>;
  /** aud が web-app の ID トークン。api-service 宛てではないので、厳格な API なら 401 になります */
  readonly idToken: string;
};

export type CallbackObservation = {
  readonly verifiesState: boolean;
  readonly verifiesIssuer: boolean;
  /** 正しいコールバックを受理できたか。false なら「何でも拒否する受け口」で、上の 2 つは当てにできません */
  readonly acceptsOwnCallback: boolean;
};

export type ObservedDefenses = CallbackObservation & {
  readonly redirectMatching: RedirectMatching;
  readonly verifiesAudience: boolean;
};

const PROBE_STATE = "probe-state";
const PROBE_VERIFIER = "probe-code-verifier";
const LEGITIMATE_URI = "http://localhost:3100/callback";

/** プローブに使う「横取りに使える宛先」。問題 1 の監査結果をそのまま使い、判定を二重に持ちません */
const HIJACKABLE_URIS = hijackableUris([LEGITIMATE_URI, "http://localhost:3100/legacy-redirect"]);

/** 受け口に 1 本コールバックを流し、受理したか（例外を投げなかったか）を返します */
function accepts(
  makeStore: () => ProbeableStore,
  expectedIssuer: string,
  callback: Record<string, string>,
): boolean {
  const store = makeStore();
  store.remember({ state: PROBE_STATE, codeVerifier: PROBE_VERIFIER, expectedIssuer });
  try {
    store.consume(new URLSearchParams(callback));
    return true;
  } catch {
    return false;
  }
}

/**
 * 受け口に 3 通りのコールバックを流し、state と iss を照合しているかを挙動から判定します。
 * 設定表を読むのではなく、拒否されるかどうかだけを根拠にします。
 */
export function observeCallbackChecks(
  makeStore: () => ProbeableStore,
  expectedIssuer: string,
): CallbackObservation {
  // 1. 対照。自分が始めたログインの正しいコールバック。これを拒否する受け口では測れない
  const own = accepts(makeStore, expectedIssuer, {
    state: PROBE_STATE,
    code: "probe-code",
    iss: expectedIssuer,
  });
  // 2. state だけ違えたコールバック。受理されたら state を見ていない
  const foreignState = accepts(makeStore, expectedIssuer, {
    state: "state-the-rp-never-issued",
    code: "probe-code",
    iss: expectedIssuer,
  });
  // 3. iss だけ違えたコールバック。state は合っているので、受理されたら iss を見ていない
  const foreignIssuer = accepts(makeStore, expectedIssuer, {
    state: PROBE_STATE,
    code: "probe-code",
    iss: "http://evil.example/realms/evil",
  });
  return { acceptsOwnCallback: own, verifiesState: !foreignState, verifiesIssuer: !foreignIssuer };
}

/** 照合関数に正当な宛先と横取りに使える宛先を通し、照合方式を推定します */
export function observeRedirectMatching(matchesRedirect: (uri: string) => boolean): RedirectMatching {
  if (!matchesRedirect(LEGITIMATE_URI)) return "none";
  return HIJACKABLE_URIS.some((uri) => matchesRedirect(uri)) ? "wildcard" : "exact";
}

/** ID トークン（aud は web-app）を投げます。401 で拒否するなら aud を検証しています */
export async function observeAudienceVerification(api: Hono<ApiEnv>, idToken: string): Promise<boolean> {
  const res = await api.request("/api/whoami", { headers: { authorization: `Bearer ${idToken}` } });
  return res.status === 401;
}

/** 4 つの防御を挙動から測ります。PKCE はコールバックからは見えないので対象外です */
export async function observeLoginDefenses(targets: ObservationTargets): Promise<ObservedDefenses> {
  return {
    ...observeCallbackChecks(targets.makeStore, targets.expectedIssuer),
    redirectMatching: observeRedirectMatching(targets.matchesRedirect),
    verifiesAudience: await observeAudienceVerification(targets.api, targets.idToken),
  };
}

// ── 設定表と挙動の突き合わせ ─────────────────────────────────────────────

export type ReconciledVerdict = "一致" | "設定はあるのに動いていない" | "設定に無いが動いている";

export type ReconciledRow = {
  readonly name: string;
  readonly declared: boolean;
  readonly observed: boolean;
  readonly verdict: ReconciledVerdict;
};

export type ReconciledReport = {
  readonly rows: ReconciledRow[];
  /** 設定はあるのに動いていない防御。もっとも危険な食い違い */
  readonly unimplemented: string[];
  /** 設定に書かれていないのに動いている防御。設定表の更新漏れ */
  readonly undocumented: string[];
  /** 測定そのものが成り立ったか（正しいコールバックを受理できたか） */
  readonly measurable: boolean;
  /** 設定表の点検が secure で、測定が成立し、食い違いが 1 つも無いときだけ true */
  readonly trustworthy: boolean;
};

/** PKCE を除く 4 つの防御について、設定表の値と挙動の値を並べて食い違いを取り出します */
export function reconcileDefenses(declared: LoginConfig, observed: ObservedDefenses): ReconciledReport {
  const pairs: readonly { name: string; declared: boolean; observed: boolean }[] = [
    { name: "state", declared: declared.verifiesState, observed: observed.verifiesState },
    { name: "iss", declared: declared.verifiesIssuer, observed: observed.verifiesIssuer },
    {
      name: "redirect_uri 完全一致",
      declared: declared.redirectMatching === "exact",
      observed: observed.redirectMatching === "exact",
    },
    { name: "aud", declared: declared.verifiesAudience, observed: observed.verifiesAudience },
  ];
  const rows: ReconciledRow[] = pairs.map((pair) => ({
    ...pair,
    verdict: pair.declared === pair.observed
      ? "一致"
      : pair.declared
        ? "設定はあるのに動いていない"
        : "設定に無いが動いている",
  }));
  const named = (verdict: ReconciledVerdict): string[] =>
    rows.filter((row) => row.verdict === verdict).map((row) => row.name);
  const unimplemented = named("設定はあるのに動いていない");
  const undocumented = named("設定に無いが動いている");
  return {
    rows,
    unimplemented,
    undocumented,
    measurable: observed.acceptsOwnCallback,
    trustworthy:
      auditLoginDefenses(declared).secure &&
      observed.acceptsOwnCallback &&
      unimplemented.length === 0 &&
      undocumented.length === 0,
  };
}

/** 設定表の点検結果を、レビューに貼れる Markdown 表にします（判定と表示を分けておく） */
export function toMarkdown(report: DefenseReport): string {
  const header = "| 防御 | 有効 | 何を防ぐか |\n| :--- | :--- | :--- |";
  const rows = report.checks.map((c) => `| ${c.name} | ${c.ok ? "○" : "×"} | ${c.note} |`);
  const verdict = report.secure ? "すべての防御が有効です" : `欠けている防御: ${report.missing.join(", ")}`;
  return [header, ...rows, "", verdict].join("\n");
}

/**
 * 観測値を設定表の形に起こします。
 * これを auditLoginDefenses に通せば、挙動からのレポートを設定表と同じ書式で出せます
 * （PKCE だけは挙動から測れないので、呼ぶ側が申告値を渡します）。
 */
export function observedToConfig(
  observed: ObservedDefenses,
  codeChallengeMethod: LoginConfig["codeChallengeMethod"],
): LoginConfig {
  return {
    codeChallengeMethod,
    verifiesState: observed.verifiesState,
    verifiesIssuer: observed.verifiesIssuer,
    redirectMatching: observed.redirectMatching,
    verifiesAudience: observed.verifiesAudience,
  };
}
