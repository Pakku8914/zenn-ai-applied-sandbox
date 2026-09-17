// セッション 13（後半）問題 6: Bearer から DPoP への段階移行を、受け入れ判定と計測に分けます。
// realm もクライアントも触りません。4 段階の計画そのものは解答の文章（表）で書きます。

/** 移行の段階。この順に進めます */
export type EnforcementMode = "bearer-only" | "observe" | "prefer" | "require";

/** 1 リクエストから読み取れる事実だけ。判定はここから導きます */
export type RequestFacts = {
  readonly scheme: "Bearer" | "DPoP";
  /** アクセストークンに cnf.jkt があるか */
  readonly bound: boolean;
  /** proof が verifyDpopProof() を通ったか（proof が無ければ false） */
  readonly proofValid: boolean;
};

export type MetricKey = "bearer_unbound" | "bearer_bound" | "dpop_ok" | "dpop_rejected";
export type Counters = Record<MetricKey, number>;

/** 事実を 4 つの計測項目に割り当てます。どの段階でも同じ分類を使います */
export function metricOf(facts: RequestFacts): MetricKey {
  if (facts.scheme === "Bearer") return facts.bound ? "bearer_bound" : "bearer_unbound";
  return facts.proofValid ? "dpop_ok" : "dpop_rejected";
}

/** observe は数えるだけで落とさず、prefer は DPoP を名乗ったものにだけ proof を要求します */
export function decide(mode: EnforcementMode, facts: RequestFacts): { allow: boolean; metric: MetricKey } {
  const metric = metricOf(facts);
  if (mode === "bearer-only" || mode === "observe") return { allow: true, metric };
  if (facts.scheme === "Bearer") return { allow: mode === "prefer", metric };
  return { allow: facts.proofValid, metric };
}

/** 観測結果を数えます。metricOf() は段階を知らないので、集計は段階を増やしても変わりません */
export function tally(requests: readonly RequestFacts[]): Counters {
  const c: Counters = { bearer_unbound: 0, bearer_bound: 0, dpop_ok: 0, dpop_rejected: 0 };
  for (const facts of requests) c[metricOf(facts)] += 1;
  return c;
}

/** 必須化を止める理由。外に返すのは識別子だけにします（前半の問題 6 と同じ作法） */
export type Blocker = "unbound_bearer" | "bound_bearer" | "no_dpop" | "high_reject" | "short_window";
export const MAX_REJECT_RATE = 0.01;
export const MIN_OBSERVED_DAYS = 14;

/** 必須化してよいか。落ちた理由を全部並べます（最初の 1 件で打ち切らない） */
export function readyToRequire(
  c: Counters,
  days: number,
): { ready: boolean; blockers: readonly Blocker[]; rejectRate: number } {
  const total = c.dpop_ok + c.dpop_rejected;
  // 1 件も観測できていないときは「判断できない」ので通しません
  const rejectRate = total === 0 ? 1 : c.dpop_rejected / total;
  const blockers: Blocker[] = [];
  if (c.bearer_unbound > 0) blockers.push("unbound_bearer");
  if (c.bearer_bound > 0) blockers.push("bound_bearer");
  if (total === 0) blockers.push("no_dpop");
  else if (rejectRate > MAX_REJECT_RATE) blockers.push("high_reject");
  if (days < MIN_OBSERVED_DAYS) blockers.push("short_window");
  return { ready: blockers.length === 0, blockers, rejectRate };
}
