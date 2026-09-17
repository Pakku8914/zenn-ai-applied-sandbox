// 問題4: メールアドレスの衝突を「自動でつなぐ」のではなく「本人確認してからつなぐ」形にする。
// 外部 IdP から来た初回ログインが email-conflict で止まったとき、その先を用意します。
import { FederatedUserStore } from "./rp-jit-provisioning.js";
import type { FederatedKey, ShopUser } from "./rp-jit-provisioning.js";

/** 確認コードの有効期間（秒）。短すぎると届く前に切れ、長すぎると盗み見の猶予を与えます */
export const LINK_CODE_TTL = 600;

export type LinkChallenge = {
  readonly challengeId: string;
  readonly key: FederatedKey;
  readonly userId: string;
  readonly code: string;
  readonly expiresAt: number;
  readonly used: boolean;
};

export type LinkFailure = "not-found" | "wrong-code" | "expired" | "used" | "deactivated";

export type LinkOutcome =
  | { readonly ok: true; readonly user: ShopUser }
  | { readonly ok: false; readonly failure: LinkFailure };

/**
 * アカウントリンクの申し込みと確認。
 * コードの生成は外から差し込みます（検証で結果を固定できるようにするため）。
 * 本番では暗号論的乱数を使い、コードは登録済みの連絡先にだけ送ります。
 */
export class AccountLinkFlow {
  private readonly challenges = new Map<string, LinkChallenge>();
  private sequence = 0;

  constructor(
    private readonly store: FederatedUserStore,
    private readonly generateCode: () => string,
  ) {}

  /** 衝突した相手の利用者 ID を指定して、確認コードを発行します */
  begin(key: FederatedKey, userId: string, now: number): LinkChallenge {
    this.sequence += 1;
    const challenge: LinkChallenge = {
      challengeId: `link-${this.sequence}`,
      key,
      userId,
      code: this.generateCode(),
      expiresAt: now + LINK_CODE_TTL,
      used: false,
    };
    this.challenges.set(challenge.challengeId, challenge);
    return challenge;
  }

  /** コードが一致したときだけ、既存レコードに連携鍵を結び付けます */
  confirm(challengeId: string, code: string, now: number): LinkOutcome {
    const challenge = this.challenges.get(challengeId);
    if (challenge === undefined) {
      return { ok: false, failure: "not-found" };
    }
    if (challenge.used) {
      return { ok: false, failure: "used" };
    }
    if (now > challenge.expiresAt) {
      return { ok: false, failure: "expired" };
    }
    if (code !== challenge.code) {
      // 間違ったコードでは使用済みにしません（打ち間違いで詰むため）。試行回数は別に数えます
      return { ok: false, failure: "wrong-code" };
    }
    this.challenges.set(challenge.challengeId, { ...challenge, used: true });
    const result = this.store.linkExisting(challenge.key, challenge.userId);
    if (result.outcome === "rejected") {
      return { ok: false, failure: "deactivated" };
    }
    return { ok: true, user: result.user };
  }

  /** 保留中の申し込みの数（検証用） */
  get pending(): number {
    return [...this.challenges.values()].filter((challenge) => !challenge.used).length;
  }
}

/** 検証で結果を固定するための、順番に配る偽のコード生成器 */
export const sequentialCodes = (codes: readonly string[]): (() => string) => {
  let index = 0;
  return () => {
    const code = codes[index] ?? "000000";
    index += 1;
    return code;
  };
};
