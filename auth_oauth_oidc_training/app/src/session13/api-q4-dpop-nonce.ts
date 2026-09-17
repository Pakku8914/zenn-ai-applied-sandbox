// セッション 13 問題 4 の発展: リソースサーバーが nonce を配り、proof にそれを含めさせます（RFC 9449 §8）。
// 問題 4 で作った dpopAuth() は変えず、そのうしろに 1 段足す形にします。
import { randomUUID } from "node:crypto";
import { Hono } from "hono";
import { createMiddleware } from "hono/factory";
import type { ProofReplayGuard } from "./api-service-dpop.js";
import { dpopAuth, rejectDpop } from "./api-q4-dpop-middleware.js";
import type { DpopEnv } from "./api-q4-dpop-middleware.js";

/** 配った nonce が有効な秒数 */
export const NONCE_LIFETIME_SECONDS = 60;
/** nonce を返すヘッダの名前（RFC 9449） */
export const NONCE_HEADER = "dpop-nonce";

/** サーバーが配った nonce を覚えておく入れ物 */
export class NonceIssuer {
  private readonly issued = new Map<string, number>();
  private readonly lifetimeSeconds: number;

  constructor(lifetimeSeconds: number = NONCE_LIFETIME_SECONDS) {
    this.lifetimeSeconds = lifetimeSeconds;
  }

  /** 新しい nonce を 1 つ作って覚えます。期限切れのものはここで忘れます */
  issue(now: number): string {
    for (const [nonce, at] of this.issued) {
      if (at + this.lifetimeSeconds < now) this.issued.delete(nonce);
    }
    const nonce = randomUUID();
    this.issued.set(nonce, now);
    return nonce;
  }

  /** 自分が配ったもので、かつ期限内か。知らない値は受け付けません */
  isValid(nonce: unknown, now: number): boolean {
    if (typeof nonce !== "string") return false;
    const issuedAt = this.issued.get(nonce);
    return issuedAt !== undefined && issuedAt + this.lifetimeSeconds >= now;
  }

  get size(): number {
    return this.issued.size;
  }
}

/**
 * proof に有効な nonce が入っていなければ、新しい nonce を渡して出し直させます。
 * dpopAuth() のうしろに置くこと（proof の署名検証が済んでいることが前提です）。
 */
export function requireDpopNonce(nonces: NonceIssuer, options: { now?: () => number } = {}) {
  const clock = options.now ?? (() => Math.floor(Date.now() / 1000));

  return createMiddleware<DpopEnv>(async (c, next) => {
    const now = clock();
    const claimed = c.get("proof")["nonce"];
    if (!nonces.isValid(claimed, now)) {
      // 拒否と同時に次に使うべき nonce を渡します。だから 1 往復で回復できます
      c.header(NONCE_HEADER, nonces.issue(now));
      return rejectDpop(c, {
        error: "use_dpop_nonce",
        description: "Use the nonce from the DPoP-Nonce header",
        message: "DPoP-Nonce の値を proof に入れて出し直してください",
      });
    }
    await next();
  });
}

export type NonceApiOptions = {
  readonly nonces?: NonceIssuer;
  readonly guard?: ProofReplayGuard;
  readonly now?: () => number;
};

export function createNonceApi(options: NonceApiOptions = {}): Hono<DpopEnv> {
  const nonces = options.nonces ?? new NonceIssuer();
  const app = new Hono<DpopEnv>();

  app.get("/health", (c) => c.json({ status: "ok", service: "api-service", accepts: "DPoP + nonce" }));

  // 検証は 2 段。1 段目で proof を確かめ、2 段目で nonce を確かめます
  app.use("/api/*", dpopAuth({ guard: options.guard, now: options.now }), requireDpopNonce(nonces, { now: options.now }));

  app.get("/api/summary", (c) =>
    c.json({ client: c.get("claims").azp ?? null, jkt: c.get("jkt"), nonce: c.get("proof")["nonce"] ?? null }),
  );

  return app;
}
