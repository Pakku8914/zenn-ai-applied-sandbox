// 問題 4 の解答: JWKS を自分でキャッシュし、知らない kid のときだけ取り直す最小実装。
// jose の createRemoteJWKSet が内部でやっていることを、回数を数えられる形で書き出したものです。
import { createLocalJWKSet, jwtVerify } from "jose";
import type { JSONWebKeySet, JWTPayload } from "jose";
import { AUDIENCE, ISSUER, JWKS_URI } from "../session04/bookstore-endpoints.js";

/** jose が「JWKS に合う鍵が無い」ときに投げるエラーかどうか */
export function isNoMatchingKey(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    (err as { code?: unknown }).code === "ERR_JWKS_NO_MATCHING_KEY"
  );
}

export type JwksCacheOptions = {
  /** 取り直しの最短間隔（ミリ秒）。短い間隔で叩かれても認可サーバーに行かないための歯止め */
  cooldownMs?: number;
};

export class JwksCache {
  /** JWKS を取りに行った回数（ネットワークに出た回数） */
  public fetchCount = 0;
  private keySet: JSONWebKeySet = { keys: [] };
  private lastFetchedAt = 0;
  private readonly cooldownMs: number;

  constructor(options: JwksCacheOptions = {}) {
    this.cooldownMs = options.cooldownMs ?? 30_000;
  }

  /** 手元に持っている鍵の kid 一覧 */
  get kids(): string[] {
    return this.keySet.keys
      .map((key) => (typeof key.kid === "string" ? key.kid : ""))
      .filter((kid) => kid !== "");
  }

  /** JWKS を取り直します。cooldown 中は取りに行かず false を返します */
  async refresh(now: number = Date.now()): Promise<boolean> {
    if (this.fetchCount > 0 && now - this.lastFetchedAt < this.cooldownMs) return false;
    const res = await fetch(JWKS_URI);
    if (!res.ok) throw new Error(`JWKS の取得に失敗しました: HTTP ${res.status}`);
    this.keySet = (await res.json()) as JSONWebKeySet;
    this.lastFetchedAt = now;
    this.fetchCount += 1;
    return true;
  }

  /** 手元の鍵で検証し、kid が見つからないときだけ 1 回取り直して再試行します */
  async verify(token: string): Promise<JWTPayload> {
    if (this.fetchCount === 0) await this.refresh();
    try {
      return await this.verifyWithCachedKeys(token);
    } catch (err) {
      if (!isNoMatchingKey(err)) throw err; // 署名不一致や期限切れは取り直しても直らない
      const refreshed = await this.refresh();
      if (!refreshed) {
        throw new Error("知らない kid ですが、取り直しの間隔が短すぎるため取りに行きません（cooldown）");
      }
      return await this.verifyWithCachedKeys(token);
    }
  }

  private async verifyWithCachedKeys(token: string): Promise<JWTPayload> {
    const getKey = createLocalJWKSet(this.keySet); // 手元の鍵束から kid で選ぶ
    const { payload } = await jwtVerify(token, getKey, {
      algorithms: ["RS256"],
      issuer: ISSUER,
      audience: AUDIENCE,
      clockTolerance: 5,
    });
    return payload;
  }
}
