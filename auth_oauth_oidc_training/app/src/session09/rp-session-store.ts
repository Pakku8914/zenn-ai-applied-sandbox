// RP のセッション置き場。Cookie に入れるのはここで発行した ID だけで、
// トークンはすべてサーバー側（このストア）に置きます。
// セッション 3 の SessionStore と同じ考え方（ID の再生成・2 本の期限）を、トークン用に作り直したものです。
import { randomBytes } from "node:crypto";

/** Cookie の名前。セッション 3 の書店（sid）とは別のアプリなので名前を分けます */
export const SESSION_COOKIE = "rp_sid";

/** 開始したがまだ終わっていないログイン。state・nonce・code_verifier の 3 点セット */
export type LoginAttempt = { readonly state: string; readonly nonce: string; readonly codeVerifier: string };

/** ID トークンから取り出した「誰か」。画面に出す分だけ持ちます */
export type AuthenticatedUser = { readonly sub: string; readonly username: string; readonly name: string };

/** サーバー側だけに置くトークン。ブラウザには 1 文字も渡しません */
export type StoredTokens = {
  readonly accessToken: string;
  readonly refreshToken: string | undefined;
  /** RP-initiated logout の id_token_hint に使うので、使い終わっても捨てずに持っておく */
  readonly idToken: string;
  readonly accessTokenExpiresAt: number;
};

export type RpSession = {
  readonly createdAt: number; // 絶対有効期限の起点
  lastSeenAt: number; // アイドル有効期限の起点
  attempt: LoginAttempt | undefined; // ログイン中だけ入っている
  user: AuthenticatedUser | undefined; // ログイン後だけ入っている
  tokens: StoredTokens | undefined;
};

export type RpSessionStoreOptions = {
  idleTimeoutMs?: number; // 無操作で切れるまでの時間（既定 30 分）
  absoluteTimeoutMs?: number; // ログインから必ず切れるまでの時間（既定 12 時間）
  now?: () => number; // 時計。テストでは好きな時刻を差し込める
};

export function newSessionId(): string {
  // 「当てられないこと」が唯一の防御なので暗号論的乱数を使う。32 バイト = base64url で 43 文字
  return randomBytes(32).toString("base64url");
}

export class RpSessionStore {
  private readonly sessions = new Map<string, RpSession>();
  private readonly idleTimeoutMs: number;
  private readonly absoluteTimeoutMs: number;
  private readonly now: () => number;

  constructor(options: RpSessionStoreOptions = {}) {
    this.idleTimeoutMs = options.idleTimeoutMs ?? 30 * 60 * 1000;
    this.absoluteTimeoutMs = options.absoluteTimeoutMs ?? 12 * 60 * 60 * 1000;
    this.now = options.now ?? (() => Date.now());
  }

  /** ログインを開始する。この時点では「誰か」はまだ分かっていない */
  startLogin(attempt: LoginAttempt): { id: string; session: RpSession } {
    const id = newSessionId();
    const at = this.now();
    const session: RpSession = { createdAt: at, lastSeenAt: at, attempt, user: undefined, tokens: undefined };
    this.sessions.set(id, session);
    return { id, session };
  }

  /** ID からセッションを引く。期限切れなら取得できず、サーバー側からも消える */
  get(id: string | undefined): RpSession | undefined {
    const session = id === undefined ? undefined : this.sessions.get(id);
    if (id === undefined || session === undefined) {
      return undefined;
    }
    const at = this.now();
    // アイドル期限（前回アクセスから）と絶対期限（ログインから）の 2 本を別々に見る
    if (at - session.lastSeenAt > this.idleTimeoutMs || at - session.createdAt > this.absoluteTimeoutMs) {
      this.sessions.delete(id);
      return undefined;
    }
    session.lastSeenAt = at;
    return session;
  }

  /**
   * ログイン成功時に呼ぶ。中身を新しい ID に移し替え、古い ID を無効化する。
   * セッション 3 で見たセッション固定攻撃の対策を、OIDC のログインでもそのまま行う。
   */
  completeLogin(
    oldId: string | undefined,
    args: { user: AuthenticatedUser; tokens: StoredTokens },
  ): { id: string; session: RpSession } {
    this.destroy(oldId); // ログイン前の ID は無効にする
    const id = newSessionId();
    const at = this.now(); // 絶対有効期限の起点はログイン時刻にそろえる
    // attempt を undefined にして、使い終わった state / nonce / code_verifier を残さない
    const session: RpSession = { createdAt: at, lastSeenAt: at, attempt: undefined, user: args.user, tokens: args.tokens };
    this.sessions.set(id, session);
    return { id, session };
  }

  /** ログアウト。サーバー側の記録（トークンを含む）を消すことが本体 */
  destroy(id: string | undefined): void {
    if (id !== undefined) {
      this.sessions.delete(id);
    }
  }

  /** 保管中のセッション数（検証用） */
  get size(): number {
    return this.sessions.size;
  }
}
