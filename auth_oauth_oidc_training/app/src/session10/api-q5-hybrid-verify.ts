// 問題 5 の解答: ローカル検証を必ず先に行い、重い操作のときだけイントロスペクションを足す検証器。
import { createHash } from "node:crypto";
import { verifyAccessToken } from "../session04/api-service-verify-jwt.js";
import { toAccessTokenClaims } from "./api-service-claims.js";
import type { AccessTokenClaims } from "./api-service-claims.js";
import { introspect } from "./api-service-introspect.js";

export type HybridOptions = {
  /** イントロスペクションの結果を使い回す時間（ミリ秒）。0 なら毎回問い合わせる */
  cacheTtlMs?: number;
  now?: () => number;
};

export type HybridResult = {
  claims: AccessTokenClaims;
  /** 判断に使った情報の出どころ */
  source: "local" | "introspection" | "introspection-cache";
  /** 認可サーバーに聞いていない場合は null（「生きている」とは言い切れない） */
  active: boolean | null;
};

export class HybridVerifier {
  /** 認可サーバーに問い合わせた回数 */
  public introspectionCalls = 0;
  private readonly cache = new Map<string, { active: boolean; expiresAt: number }>();
  private readonly cacheTtlMs: number;
  private readonly now: () => number;

  constructor(options: HybridOptions = {}) {
    this.cacheTtlMs = options.cacheTtlMs ?? 10_000;
    this.now = options.now ?? (() => Date.now());
  }

  /** トークンそのものをキーにしない（ログやダンプに生のトークンを残さないため） */
  private static keyOf(token: string): string {
    return createHash("sha256").update(token).digest("base64url").slice(0, 16);
  }

  async verify(token: string, options: { sensitive: boolean }): Promise<HybridResult> {
    // 1. まず手元で検証する。ここを通らないトークンは問い合わせる価値もない
    const claims = toAccessTokenClaims((await verifyAccessToken(token)).payload);
    if (!options.sensitive) {
      return { claims, source: "local", active: null };
    }

    // 2. 重い操作のときだけ認可サーバーに現状を聞く（短い時間だけ結果を使い回す）
    const key = HybridVerifier.keyOf(token);
    const cached = this.cache.get(key);
    const nowMs = this.now();
    if (cached !== undefined && cached.expiresAt > nowMs) {
      return { claims, source: "introspection-cache", active: cached.active };
    }

    const { active } = await introspect(token);
    this.introspectionCalls += 1;
    this.cache.set(key, { active, expiresAt: nowMs + this.cacheTtlMs });
    return { claims, source: "introspection", active };
  }
}
