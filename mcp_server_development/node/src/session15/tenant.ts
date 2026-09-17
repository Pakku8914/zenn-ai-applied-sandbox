/**
 * テナント登録簿とセッション単位のサーバー生成
 *
 * テナント境界を「セッション」に置きます。接続ごとに、そのテナントの docsRoot を
 * 束縛したサーバー実例を作るので、実行中に検索対象を差し替えられません。
 * 共有するのはレート制限のバケット表だけで、キーにテナントIDを含めます。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createAuditLogger } from "./audit-log.js";
import { createGuardedDocSearchServer } from "./guarded-server.js";
import { type RateLimiter, createRateLimiter } from "./rate-limit.js";

export type TenantConfig = {
  readonly tenantId: string;
  readonly docsRoot: string;
  /** そのテナントに許す瞬間的な呼び出し回数 */
  readonly capacity: number;
  readonly refillPerSecond: number;
};

export type SessionContext = {
  readonly tenantId: string;
  readonly subjectId: string;
  readonly sessionId: string;
};

export type TenantRegistryOptions = {
  readonly tenants: readonly TenantConfig[];
  readonly now: () => number;
  readonly pepper: string;
  readonly sink?: (line: string) => void;
  readonly nonce?: () => string;
};

export type TenantRegistry = {
  serverFor(session: SessionContext): McpServer;
  close(sessionId: string): void;
  activeSessions(): number;
};

export class UnknownTenantError extends Error {
  constructor() {
    // テナントIDを文面に入れない（存在するIDの探索に使われる）
    super("指定されたテナントは登録されていません。");
    this.name = "UnknownTenantError";
  }
}

export class SessionConflictError extends Error {
  constructor() {
    super("同じセッションIDが別のテナントで再利用されています。");
    this.name = "SessionConflictError";
  }
}

export function createTenantRegistry(options: TenantRegistryOptions): TenantRegistry {
  const configs = new Map(options.tenants.map((tenant) => [tenant.tenantId, tenant]));
  // レート制限はテナントごとに 1 つ。全体で 1 つにすると 1 テナントの暴走が全員を止める
  const limiters = new Map<string, RateLimiter>();
  const servers = new Map<string, { tenantId: string; server: McpServer }>();

  function limiterFor(config: TenantConfig): RateLimiter {
    const existing = limiters.get(config.tenantId);
    if (existing !== undefined) {
      return existing;
    }
    const created = createRateLimiter({
      capacity: config.capacity,
      refillPerSecond: config.refillPerSecond,
      now: options.now,
    });
    limiters.set(config.tenantId, created);
    return created;
  }

  function serverFor(session: SessionContext): McpServer {
    const cached = servers.get(session.sessionId);
    if (cached !== undefined) {
      // セッションIDの取り違えでテナントを跨がせない
      if (cached.tenantId !== session.tenantId) {
        throw new SessionConflictError();
      }
      return cached.server;
    }

    const config = configs.get(session.tenantId);
    if (config === undefined) {
      throw new UnknownTenantError();
    }

    const audit = createAuditLogger({
      server: "docsearch-guarded",
      tenantId: config.tenantId,
      subjectId: session.subjectId,
      sessionId: session.sessionId,
      pepper: options.pepper,
      clock: options.now,
      ...(options.sink === undefined ? {} : { sink: options.sink }),
    });

    const server = createGuardedDocSearchServer({
      // docsRoot はここで束縛される。以降どこからも差し替えられない
      docsRoot: config.docsRoot,
      tenant: session,
      audit,
      limiter: limiterFor(config),
      clock: options.now,
      ...(options.nonce === undefined ? {} : { nonce: options.nonce }),
    });

    servers.set(session.sessionId, { tenantId: config.tenantId, server });
    return server;
  }

  return {
    serverFor,
    close: (sessionId) => {
      // 作ったものを捨てる経路まで作る。無いとセッションが増え続ける
      servers.delete(sessionId);
    },
    activeSessions: () => servers.size,
  };
}
