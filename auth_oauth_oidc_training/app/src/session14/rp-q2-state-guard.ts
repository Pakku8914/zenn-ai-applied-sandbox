// 練習問題 2: state だけを照合する最小のコールバック受け口を作り、CSRF（ログインの取り違え）を弾く。
export class StateMismatchError extends Error {}

export type PendingState = { state: string; codeVerifier: string };

/**
 * state だけを照合する入れ物。iss の照合は問題 4 で足すので、ここでは state に集中します。
 * 「自分が始めたログインか」を state で確かめるのが CSRF 対策の中心です。
 */
export class StateOnlyStore {
  private readonly pending = new Map<string, PendingState>();

  remember(entry: PendingState): void {
    this.pending.set(entry.state, entry);
  }

  /** 覚えのない state のコールバックは拒否します。1 度使った state は捨てます */
  consume(params: URLSearchParams): { code: string; codeVerifier: string } {
    const state = params.get("state") ?? "";
    const entry = this.pending.get(state);
    if (entry === undefined) {
      throw new StateMismatchError("覚えのない state です（自分が始めたログインではありません）");
    }
    this.pending.delete(state);
    const code = params.get("code") ?? "";
    return { code, codeVerifier: entry.codeVerifier };
  }

  get size(): number {
    return this.pending.size;
  }
}

export type DrillOutcome = "accepted" | "rejected";

/** 自分のコールバックと、攻撃者が差し込んだコールバックの両方を通し、結果を並べます */
export function csrfDrill(own: URLSearchParams, foreign: URLSearchParams): {
  own: DrillOutcome;
  foreign: DrillOutcome;
} {
  const classify = (params: URLSearchParams): DrillOutcome => {
    const store = new StateOnlyStore();
    // 自分が始めたログインだけを remember する（own の state だけを覚える）
    store.remember({ state: own.get("state") ?? "", codeVerifier: "verifier-own" });
    try {
      store.consume(params);
      return "accepted";
    } catch (err) {
      if (err instanceof StateMismatchError) return "rejected";
      throw err;
    }
  };
  return { own: classify(own), foreign: classify(foreign) };
}
