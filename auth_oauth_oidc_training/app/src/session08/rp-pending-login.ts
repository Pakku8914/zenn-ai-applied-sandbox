// 認可リクエストを始めるときに作った値を、コールバックまで覚えておく入れ物。
// セッション 6 の PendingLoginStore に nonce を足したものです。
// state（CSRF 対策）と nonce（ID トークンの使い回し対策）は目的の違う別々の値なので、両方を保存します。
import { randomBytes } from "node:crypto";

export type PendingLogin = {
  readonly state: string;
  readonly nonce: string;
  readonly codeVerifier: string;
  readonly createdAt: number;
};

/** ログイン画面に 10 分以上かかることは無いので、それを過ぎた記録は捨てます */
const TTL_MS = 10 * 60 * 1000;

export class PendingLoginStore {
  private readonly pending = new Map<string, PendingLogin>();

  /** state と nonce を新しく作って覚えます。codeVerifier はセッション 6 の PKCE で作った値です */
  start(codeVerifier: string, now = Date.now()): PendingLogin {
    const login: PendingLogin = {
      // どちらも推測できてはいけないので、乱数から作ります
      state: randomBytes(16).toString("base64url"),
      nonce: randomBytes(16).toString("base64url"),
      codeVerifier,
      createdAt: now,
    };
    this.pending.set(login.state, login);
    return login;
  }

  /** state に対応する記録を 1 回だけ取り出します（2 回目は失敗します） */
  consume(state: string, now = Date.now()): PendingLogin {
    const login = this.pending.get(state);
    // 取り出せたかどうかに関わらず消す。同じコールバックを 2 回処理させないためです
    this.pending.delete(state);
    if (login === undefined) {
      throw new Error("state が一致しません（自分が始めたログインではありません）");
    }
    if (now - login.createdAt > TTL_MS) {
      throw new Error("ログインの開始から時間が経ちすぎています（やり直してください）");
    }
    return login;
  }

  get size(): number {
    return this.pending.size;
  }
}
