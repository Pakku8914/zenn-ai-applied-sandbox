/**
 * セッションの寿命管理（回収）
 *
 * DELETE は仕様上「送るべき」であって必須ではないので、送られない前提で
 * 回収する仕組みが必要です。http-server.ts は変更せず、公開インターフェース
 * （sessions() / closeSession()）だけを使って実装します。
 */
import type { SessionInfo } from "./http-server.js";

export type ReaperTarget = {
  sessions(): SessionInfo[];
  closeSession(id: string): Promise<boolean>;
};

export type ReaperOptions = {
  /** 最後のリクエストからこの時間を超えたら回収する */
  readonly idleMs: number;
  /** 作成からこの時間を超えたら（アイドルでなくても）回収する */
  readonly maxAgeMs: number;
  readonly intervalMs: number;
  /** テストから時刻を差し替えられるようにする */
  readonly now?: () => number;
};

export type Doomed = {
  readonly id: string;
  readonly reason: "idle" | "expired";
  readonly elapsedMs: number;
};

/** 判定だけを純関数として切り出す（タイマーを動かさずにテストできる） */
export function collectDoomed(
  sessions: readonly SessionInfo[],
  options: Pick<ReaperOptions, "idleMs" | "maxAgeMs">,
  now: number,
): Doomed[] {
  const doomed: Doomed[] = [];
  for (const session of sessions) {
    const age = now - session.createdAt;
    const idle = now - session.lastSeenAt;
    // 寿命超過を先に見る（アイドルでなくても閉じる必要があるため）
    if (age > options.maxAgeMs) {
      doomed.push({ id: session.id, reason: "expired", elapsedMs: age });
    } else if (idle > options.idleMs) {
      doomed.push({ id: session.id, reason: "idle", elapsedMs: idle });
    }
  }
  return doomed;
}

export function startSessionReaper(target: ReaperTarget, options: ReaperOptions): () => void {
  const now = options.now ?? (() => Date.now());

  async function sweep(): Promise<void> {
    for (const victim of collectDoomed(target.sessions(), options, now())) {
      try {
        const closed = await target.closeSession(victim.id);
        if (closed) {
          console.error(
            `[reaper] 回収: ${victim.id}（理由=${victim.reason} / 経過 ${victim.elapsedMs}ms）`,
          );
        }
      } catch (error) {
        // 1 件の失敗で走査を止めない（次の周回で再試行される）
        console.error(
          `[reaper] 回収に失敗: ${victim.id} → ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
  }

  const timer = setInterval(() => void sweep(), options.intervalMs);
  // 回収タイマーがプロセスの終了を妨げないようにする
  timer.unref();
  return () => clearInterval(timer);
}
