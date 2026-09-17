// 問題 6 の解答: localStorage にトークンを置く SPA を BFF へ移す計画を、
// 「その段階で消えた脅威」「新しく現れた脅威」「まだ残る脅威」の形で出します。
// 一番危ないのは移行の途中（両方の経路が生きている状態）だと分かるようにするのが目的です。
import { findVerdict } from "./bff-token-storage.js";
import type { StorageKind } from "./bff-token-storage.js";
import { refreshPolicyFor } from "./public-client-refresh.js";
import type { Placement } from "./public-client-refresh.js";

export type Threat =
  | "xss-token-theft"
  | "xss-request-forgery"
  | "csrf"
  | "refresh-token-longevity"
  | "session-fixation"
  | "bff-session-store";

export const THREAT_LABELS: Record<Threat, string> = {
  "xss-token-theft": "XSS でトークンそのものを持ち去られる",
  "xss-request-forgery": "XSS でブラウザに API を呼ばせられる（トークンが見えなくても実行はできる）",
  csrf: "他サイトから Cookie 付きの呼び出しをされる",
  "refresh-token-longevity": "盗まれたリフレッシュトークンが長く使える",
  "session-fixation": "ログイン前のセッション ID を使い続けられる",
  "bff-session-store": "BFF のセッションストアがトークンの集積場所になる",
};

/** 脅威を並べる順序。段階ごとの表を見比べるために固定します */
const THREAT_ORDER: readonly Threat[] = [
  "xss-token-theft",
  "xss-request-forgery",
  "csrf",
  "refresh-token-longevity",
  "session-fixation",
  "bff-session-store",
];

/**
 * その置き場所・配置形態に「構造的に付いてくる」脅威を導きます。
 * 対策を打ったかどうかは見ません（それは段階の側の情報です）。
 */
export function residualThreats(storage: StorageKind, placement: Placement): readonly Threat[] {
  const verdict = findVerdict(storage);
  const policy = refreshPolicyFor(placement);
  // Cookie で本人を確かめる構成は、置き場所が何であれ CSRF の対象になる
  const cookieBased = placement === "spa-with-bff" || placement === "server-side";
  const threats = new Set<Threat>();
  if (verdict.stolenByXss) threats.add("xss-token-theft");
  // トークンが読めなくても、XSS があればブラウザに代わりに呼ばせることはできる
  threats.add("xss-request-forgery");
  if (verdict.needsCsrfDefense || cookieBased) threats.add("csrf");
  if (policy.rotationRequired) threats.add("refresh-token-longevity");
  threats.add("session-fixation");
  if (storage === "bff-server-side") threats.add("bff-session-store");
  return THREAT_ORDER.filter((threat) => threats.has(threat));
}

export type Stage = {
  readonly order: number;
  readonly name: string;
  readonly storage: StorageKind;
  readonly placement: Placement;
  /** この段階で追加する対策 */
  readonly adds: readonly string[];
  /** その対策で消える脅威 */
  readonly mitigates: readonly Threat[];
  /** この段階を「終わった」と言うための条件 */
  readonly acceptance: readonly string[];
};

export const STAGES: readonly Stage[] = [
  {
    order: 1,
    name: "現状（トークンを localStorage に置く SPA）",
    storage: "local-storage",
    placement: "spa-token-in-browser",
    adds: [],
    mitigates: [],
    acceptance: ["現状の脅威を一覧にして関係者で合意する"],
  },
  {
    order: 2,
    name: "リフレッシュトークンのローテーションを有効にする",
    storage: "local-storage",
    placement: "spa-token-in-browser",
    adds: ["realm の revokeRefreshToken を有効にする", "再利用を検知したらセッションごと落とす"],
    mitigates: ["refresh-token-longevity"],
    acceptance: ["旧リフレッシュトークンの再利用が 400 invalid_grant になる"],
  },
  {
    order: 3,
    name: "BFF を立てて API 呼び出しだけ移す（トークンはまだブラウザにも残る）",
    storage: "local-storage",
    placement: "spa-with-bff",
    adds: [
      "セッション Cookie に HttpOnly・SameSite・Secure を付ける",
      "ログイン成功時にセッション ID を作り直す",
      "状態を変える操作を非 GET にして Origin を検査する",
    ],
    mitigates: ["session-fixation", "csrf"],
    acceptance: ["他サイトからの POST が 403 になる", "BFF の応答にトークンが含まれないことを機械検査で確かめる"],
  },
  {
    order: 4,
    name: "ブラウザからトークンを消す",
    storage: "bff-server-side",
    placement: "spa-with-bff",
    adds: ["localStorage に残った古いトークンを消す", "トークンを返していた口を削除する"],
    mitigates: [],
    acceptance: ["ブラウザの保存領域にトークンが 1 つも残っていない", "トークンを返す経路がコードに存在しない"],
  },
];

export type PlanRow = {
  readonly order: number;
  readonly name: string;
  /** 前の段階まで残っていて、この段階で消えた脅威 */
  readonly removed: readonly Threat[];
  /** この段階で新しく現れた脅威 */
  readonly added: readonly Threat[];
  readonly remaining: readonly Threat[];
  readonly acceptance: readonly string[];
};

export function buildPlan(stages: readonly Stage[] = STAGES): readonly PlanRow[] {
  const rows: PlanRow[] = [];
  const mitigated = new Set<Threat>();
  let previous: readonly Threat[] = [];
  for (const stage of stages) {
    for (const threat of stage.mitigates) {
      mitigated.add(threat);
    }
    const remaining = residualThreats(stage.storage, stage.placement).filter(
      (threat) => !mitigated.has(threat),
    );
    rows.push({
      order: stage.order,
      name: stage.name,
      removed: previous.filter((threat) => !remaining.includes(threat)),
      added: remaining.filter((threat) => !previous.includes(threat)),
      remaining,
      acceptance: stage.acceptance,
    });
    previous = remaining;
  }
  return rows;
}

const labels = (threats: readonly Threat[]): string =>
  threats.length === 0 ? "なし" : threats.map((threat) => THREAT_LABELS[threat]).join("<br>");

export function toMarkdown(rows: readonly PlanRow[] = buildPlan()): string {
  const header = "| 段階 | 内容 | 消えた脅威 | 現れた脅威 | 残る脅威 |";
  const rule = "| :--- | :--- | :--- | :--- | :--- |";
  const body = rows.map(
    (row) => `| ${row.order} | ${row.name} | ${labels(row.removed)} | ${labels(row.added)} | ${labels(row.remaining)} |`,
  );
  return [header, rule, ...body].join("\n");
}
