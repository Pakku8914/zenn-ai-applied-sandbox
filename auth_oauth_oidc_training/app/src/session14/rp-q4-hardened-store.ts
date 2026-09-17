// 練習問題 4: state・iss・使い捨ての 3 つを 1 つの受け口にまとめる（混乱した代理まで防ぐ）。
export type GuardReason = "state_mismatch" | "issuer_mismatch" | "callback_replayed" | "missing_code";

export class GuardError extends Error {
  readonly reason: GuardReason;
  constructor(reason: GuardReason, message: string) {
    super(message);
    this.reason = reason;
  }
}

export type PendingEntry = { state: string; codeVerifier: string; expectedIssuer: string };

/**
 * 1 つのコールバックにつき「state が自分のものか」「iss が期待した認可サーバーか」
 * 「まだ使っていない state か」の 3 つをまとめて確かめます。
 */
export class IssAwareStore {
  private readonly pending = new Map<string, PendingEntry>();
  private readonly used = new Set<string>();

  remember(entry: PendingEntry): void {
    this.pending.set(entry.state, entry);
  }

  consume(params: URLSearchParams): { code: string; codeVerifier: string } {
    const state = params.get("state") ?? "";
    // 使い捨て: 一度処理した state をもう一度受け付けない（コールバックのリプレイを防ぐ）
    if (this.used.has(state)) {
      throw new GuardError("callback_replayed", "このコールバックは処理済みです（同じ state の二度目）");
    }
    const entry = this.pending.get(state);
    if (entry === undefined) {
      throw new GuardError("state_mismatch", "覚えのない state です");
    }
    const iss = params.get("iss");
    if (iss !== entry.expectedIssuer) {
      this.pending.delete(state);
      this.used.add(state);
      throw new GuardError("issuer_mismatch", `iss が一致しません（期待: ${entry.expectedIssuer} / 実際: ${iss ?? "なし"}）`);
    }
    this.pending.delete(state);
    this.used.add(state);
    const code = params.get("code");
    if (code === null) {
      throw new GuardError("missing_code", "認可コードがありません");
    }
    return { code, codeVerifier: entry.codeVerifier };
  }
}
