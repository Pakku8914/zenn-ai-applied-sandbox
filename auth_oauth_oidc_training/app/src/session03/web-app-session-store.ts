// セッションの置き場所。Cookie に入れるのはここで発行した ID だけで、中身はすべてサーバー側に置きます。
import { randomBytes } from "node:crypto";

export type SessionRecord = {
  readonly createdAt: number; // 発行時刻。絶対有効期限の起点
  lastSeenAt: number; // 最後のアクセス時刻。アイドル有効期限の起点
  username: string | null; // null は未ログイン（匿名セッション）
  cart: string[]; // ログイン前から使える買い物カゴ
};

export type SessionStoreOptions = {
  idleTimeoutMs?: number; // 無操作で切れるまでの時間（既定 30 分）
  absoluteTimeoutMs?: number; // 発行から必ず切れるまでの時間（既定 12 時間）
  now?: () => number; // 時計。テストでは好きな時刻を差し込める
};

export function newSessionId(): string {
  // 「当てられないこと」が唯一の防御なので、Math.random() ではなく暗号論的乱数を使う
  // 32 バイト = 256 ビット。base64url にすると 43 文字になる
  return randomBytes(32).toString("base64url");
}

export class SessionStore {
  protected readonly sessions = new Map<string, SessionRecord>();
  private readonly idleTimeoutMs: number;
  private readonly absoluteTimeoutMs: number;
  private readonly now: () => number;

  constructor(options: SessionStoreOptions = {}) {
    this.idleTimeoutMs = options.idleTimeoutMs ?? 30 * 60 * 1000;
    this.absoluteTimeoutMs = options.absoluteTimeoutMs ?? 12 * 60 * 60 * 1000;
    this.now = options.now ?? (() => Date.now());
  }

  /** 新しいセッションを発行する。username に null を渡すと匿名セッションになる */
  create(username: string | null = null): { id: string; record: SessionRecord } {
    const id = newSessionId();
    const at = this.now();
    const record: SessionRecord = { createdAt: at, lastSeenAt: at, username, cart: [] };
    this.sessions.set(id, record);
    return { id, record };
  }

  /** ID からセッションを引く。期限切れなら取得できず、サーバー側からも消える */
  get(id: string | undefined): SessionRecord | undefined {
    if (id === undefined) {
      return undefined;
    }
    const record = this.sessions.get(id);
    if (record === undefined) {
      return undefined;
    }
    const at = this.now();
    const idleOver = at - record.lastSeenAt > this.idleTimeoutMs;
    const absoluteOver = at - record.createdAt > this.absoluteTimeoutMs;
    if (idleOver || absoluteOver) {
      this.sessions.delete(id);
      return undefined;
    }
    record.lastSeenAt = at;
    return record;
  }

  /**
   * ログイン成功時に呼ぶ。中身を新しい ID に移し替え、古い ID を無効化する。
   * これがセッション固定攻撃の対策そのものである。
   */
  regenerate(oldId: string | undefined, username: string): { id: string; record: SessionRecord } {
    const previous = oldId === undefined ? undefined : this.sessions.get(oldId);
    const id = newSessionId();
    const at = this.now();
    const record: SessionRecord = {
      createdAt: at,
      lastSeenAt: at,
      username,
      // ログイン前に入れたカートは引き継ぐ（配列はコピーして共有しない）
      cart: previous === undefined ? [] : [...previous.cart],
    };
    if (oldId !== undefined) {
      this.sessions.delete(oldId);
    }
    this.sessions.set(id, record);
    return { id, record };
  }

  /** ログアウト。サーバー側の記録を消すことが本体 */
  destroy(id: string | undefined): void {
    if (id !== undefined) {
      this.sessions.delete(id);
    }
  }
}
