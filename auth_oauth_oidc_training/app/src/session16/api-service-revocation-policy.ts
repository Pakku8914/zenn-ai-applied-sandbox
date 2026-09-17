// トークンの失効。JWT は「検証に外部の状態が要らない」ことが取り柄なので、
// 失効させるには取り柄を捨てる（問い合わせる・状態を持つ）か、寿命で押し切るしかありません。
// 3 つの選択肢を同じ尺度で比べられる形にします。
import { CLIENT_ID } from "../session06/bookstore-client.js";
import { ISSUER } from "./bookstore-keys.js";

export type RevocationStrategy = "blacklist" | "introspection" | "short-lifetime";

export type RevocationInput = {
  /** アクセストークンの寿命（秒） */
  readonly accessTokenLifespan: number;
  /** ブロックリストを全ノードに配り終えるまでの秒数 */
  readonly blacklistPropagationSeconds: number;
  /** 問い合わせ結果を手元に置く秒数（0 なら毎回聞く） */
  readonly introspectionCacheSeconds: number;
};

const DELAY: Readonly<Record<RevocationStrategy, (input: RevocationInput) => number>> = {
  // 決めた瞬間に書けるが、全ノードが読めるまでの遅れが残る
  blacklist: (input) => input.blacklistPropagationSeconds,
  // 認可サーバーが真実を持つので、キャッシュを置かなければ遅れは 0
  introspection: (input) => input.introspectionCacheSeconds,
  // 何も足さない代わりに、寿命が切れるまで待つ
  "short-lifetime": (input) => input.accessTokenLifespan,
};

/** 失効を決めてから、どのノードでも効くまでの最大の遅れ（秒） */
export function worstCaseDelaySeconds(strategy: RevocationStrategy, input: RevocationInput): number {
  return DELAY[strategy](input);
}

/** 要件（何秒以内に効かせたいか）を満たせる方式だけを並べます。無ければ寿命を短くする以外にありません */
export function strategiesWithin(seconds: number, input: RevocationInput): RevocationStrategy[] {
  return (["short-lifetime", "blacklist", "introspection"] as const).filter(
    (strategy) => worstCaseDelaySeconds(strategy, input) <= seconds,
  );
}

/**
 * 失効したトークンを jti で 1 本ずつ覚えます。
 * 要点は「exp を過ぎた分を捨てられる」こと。寿命が短いほどこの表は小さくなります。
 */
export class JtiDenyList {
  /** jti → そのトークンの exp（epoch 秒） */
  private readonly denied = new Map<string, number>();

  revoke(jti: string, expiresAt: number): void {
    this.denied.set(jti, Math.max(this.denied.get(jti) ?? 0, expiresAt));
  }

  isRevoked(jti: string): boolean {
    return this.denied.has(jti);
  }

  /** exp を過ぎた記録を捨てます。捨てても安全なのは、検証側が exp を見ているからです */
  purgeExpired(nowSeconds: number): number {
    let removed = 0;
    for (const [jti, expiresAt] of this.denied) {
      if (expiresAt <= nowSeconds) {
        this.denied.delete(jti);
        removed += 1;
      }
    }
    return removed;
  }

  get size(): number {
    return this.denied.size;
  }
}

/** RFC 7009 の失効エンドポイント（discovery の revocation_endpoint と同じ URL） */
export const REVOCATION_ENDPOINT = `${ISSUER}/protocol/openid-connect/revoke`;

/** 失効を頼みます。成功しても本文は返りません（200 で空） */
export async function revokeToken(
  token: string,
  hint: "refresh_token" | "access_token",
): Promise<{ status: number; body: string }> {
  const res = await fetch(REVOCATION_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: CLIENT_ID, token, token_type_hint: hint }),
  });
  return { status: res.status, body: await res.text() };
}
