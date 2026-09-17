// 最終プロジェクト final01: アクセストークンを使う直前に必ず通す関門。
// 認可サーバーはリフレッシュのたびに新しいリフレッシュトークンを返しますが、
// 古いトークンを使えなくするかどうかは realm の設定次第です（セッション 7 の実測）。
// そこでクライアント側でも 1 度使ったトークンを覚え、2 度目の使用を異常として扱います。
import { createHash } from "node:crypto";
import { refreshAccessToken } from "../session07/rp-refresh.js";
import type { StoredTokens } from "../session09/rp-session-store.js";

/** 期限の何秒前から取り直すか（セッション 7 と同じ 30 秒の前倒し） */
export const REFRESH_SKEW_SECONDS = 30;

/**
 * リフレッシュトークンの使用履歴。
 * トークン本体は覚えず、ハッシュの先頭 16 文字だけを手がかりにします。
 * 形式は認可サーバーの自由（不透明な文字列でよい）なので、中身を読まずに扱えるこの形にします。
 */
export class RefreshRotation {
  private readonly used = new Map<string, number>();

  handleOf(refreshToken: string): string {
    return createHash("sha256").update(refreshToken).digest().toString("base64url").slice(0, 16);
  }

  isUsed(refreshToken: string): boolean {
    return this.used.has(this.handleOf(refreshToken));
  }

  markUsed(refreshToken: string, at: number = Date.now()): string {
    const handle = this.handleOf(refreshToken);
    this.used.set(handle, at);
    return handle;
  }

  /** 使用済みの印を取り消す（新しいリフレッシュトークンが返らなかったときだけ使う） */
  unmark(refreshToken: string): void {
    this.used.delete(this.handleOf(refreshToken));
  }

  /** 覚えている件数（検証用） */
  get size(): number {
    return this.used.size;
  }
}

/** 関門の結果。トークンを受け取るか、落とす理由を受け取るかのどちらかです */
export type TokenGuardResult =
  | { readonly kind: "ok"; readonly accessToken: string; readonly refreshed: boolean }
  /** 使用済みのリフレッシュトークンが再び現れた。セッションを落とす */
  | { readonly kind: "reuse_detected" }
  /** 取り直せない。もう一度ログインしてもらう */
  | { readonly kind: "expired" };

/** トークンを預かっている入れ物。RpSession がそのまま当てはまります */
export type TokenHolder = { tokens: StoredTokens | undefined };

export async function guardAccessToken(
  holder: TokenHolder,
  rotation: RefreshRotation,
  now: number = Date.now(),
): Promise<TokenGuardResult> {
  const tokens = holder.tokens;
  if (tokens === undefined) {
    return { kind: "expired" };
  }
  // まだ余裕があるならそのまま使う（30 秒の前倒しは通信中に切れるのを避けるため）
  if (now < tokens.accessTokenExpiresAt - REFRESH_SKEW_SECONDS * 1000) {
    return { kind: "ok", accessToken: tokens.accessToken, refreshed: false };
  }
  const refreshToken = tokens.refreshToken;
  if (refreshToken === undefined || refreshToken === "") {
    return { kind: "expired" };
  }
  // 再利用の検知。盗んだ側と本物の両方が同じトークンを使うので、2 度目で必ず気づけます
  if (rotation.isUsed(refreshToken)) {
    return { kind: "reuse_detected" };
  }
  // 応答が返る前に印を付ける。通信が切れても、認可サーバー側では発行済みかもしれない
  rotation.markUsed(refreshToken, now);
  try {
    const renewed = await refreshAccessToken({ refreshToken });
    const next = renewed.refresh_token;
    if (next === undefined || next === "") {
      // 新しいトークンを返さない認可サーバーでは手元のものを使い続けるので、印を戻す
      rotation.unmark(refreshToken);
    }
    holder.tokens = {
      accessToken: renewed.access_token,
      refreshToken: next ?? refreshToken,
      // ID トークンはログアウトの id_token_hint に使うので、返らなければ手元のものを残す
      idToken: renewed.id_token ?? tokens.idToken,
      accessTokenExpiresAt: now + renewed.expires_in * 1000,
    };
    return { kind: "ok", accessToken: renewed.access_token, refreshed: true };
  } catch {
    // リフレッシュトークンの期限切れ・失効は異常ではなく想定内の結果
    return { kind: "expired" };
  }
}
