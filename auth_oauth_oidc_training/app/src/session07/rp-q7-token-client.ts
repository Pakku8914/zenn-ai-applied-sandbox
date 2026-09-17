// 練習問題 7: 同時に何本の API を呼んでもリフレッシュを 1 回にまとめるトークン保管庫。
import { refreshAccessToken } from "./rp-refresh.js";
import { DEFAULT_SKEW_SECONDS, canRefresh, needsRefresh, toTokenSet } from "./rp-token-store.js";
import type { TokenResponseLike, TokenSet } from "./rp-token-store.js";

/** リフレッシュの実処理。既定は本物の認可サーバー。テストでは偽物を差し込めるようにする */
export type RefreshFn = (refreshToken: string) => Promise<TokenResponseLike>;

const defaultRefresh: RefreshFn = (refreshToken) => refreshAccessToken({ refreshToken });

export class TokenClient {
  private set: TokenSet;
  private readonly refresh: RefreshFn;
  private readonly skewSeconds: number;
  /** いま走っているリフレッシュ。2 本目以降はこれを待ち合わせる（single-flight） */
  private inFlight: Promise<TokenSet> | null = null;
  /** 実際に認可サーバーを呼んだ回数（検証用） */
  refreshCount = 0;

  constructor(initial: TokenSet, options: { refresh?: RefreshFn; skewSeconds?: number } = {}) {
    this.set = initial;
    this.refresh = options.refresh ?? defaultRefresh;
    this.skewSeconds = options.skewSeconds ?? DEFAULT_SKEW_SECONDS;
  }

  /** API を呼ぶ直前に呼ぶ。必要なら裏で 1 回だけリフレッシュしてから返します */
  async getAccessToken(now: number = Date.now()): Promise<string> {
    if (!needsRefresh(this.set, now, this.skewSeconds)) return this.set.accessToken;
    if (this.inFlight === null) {
      this.inFlight = this.runRefresh(now).finally(() => {
        // 成功でも失敗でも、次の要求が新しいリフレッシュを始められるように必ず片付ける
        this.inFlight = null;
      });
    }
    return (await this.inFlight).accessToken;
  }

  private async runRefresh(now: number): Promise<TokenSet> {
    if (!canRefresh(this.set, now)) {
      throw new Error("リフレッシュトークンも使えません。もう一度ログインしてもらってください");
    }
    this.refreshCount += 1;
    const res = await this.refresh(this.set.refreshToken);
    this.set = toTokenSet(res, { now: Date.now(), previous: this.set });
    return this.set;
  }

  snapshot(): TokenSet {
    return this.set;
  }
}

/** 固定の時刻（ドリルを毎回同じ結果にするため） */
export const T0 = Date.parse("2026-09-08T09:00:00Z");

/** T0 の時点で受け取った、T0 + 300 秒で切れるトークン */
export function expiredTokenSet(): TokenSet {
  return toTokenSet(
    {
      access_token: "access-0",
      refresh_token: "refresh-0",
      expires_in: 300,
      refresh_expires_in: 1800,
      scope: "openid",
    },
    { now: T0 },
  );
}

export async function runConcurrencyDrill(): Promise<string[]> {
  const lines = ["=== 同時アクセス時のリフレッシュ回数 ==="];
  const now = T0 + 300_000; // アクセストークンの期限ちょうど

  let issued = 0;
  const slowRefresh: RefreshFn = async (refreshToken) => {
    // 通信の遅さを再現する。この間に来た要求が待ち合わせできるかが論点
    await new Promise((resolve) => setTimeout(resolve, 20));
    issued += 1;
    return {
      access_token: `access-${issued}`,
      refresh_token: `${refreshToken}-${issued}`,
      expires_in: 300,
      refresh_expires_in: 1800,
      scope: "openid",
    };
  };

  const client = new TokenClient(expiredTokenSet(), { refresh: slowRefresh });
  const tokens = await Promise.all(Array.from({ length: 10 }, () => client.getAccessToken(now)));
  lines.push(`同時に 10 本が要求したときのリフレッシュ回数: ${client.refreshCount}`);
  lines.push(`10 本すべてが同じアクセストークンを受け取った: ${new Set(tokens).size === 1}`);
  lines.push(`受け取ったアクセストークン: ${tokens[0] ?? "(なし)"}`);

  // 更新直後は期限まで余裕があるので、もう一度呼んでもリフレッシュは起きない
  await client.getAccessToken(Date.now());
  lines.push(`更新直後の要求でリフレッシュは増えない: ${client.refreshCount === 1}`);

  // リフレッシュトークンまで切れていたら、認可サーバーを呼ばずに再ログインを促す
  const dead = new TokenClient(expiredTokenSet(), { refresh: slowRefresh });
  let deadMessage = "";
  try {
    await dead.getAccessToken(T0 + 1_800_000);
  } catch (err) {
    deadMessage = err instanceof Error ? err.message : String(err);
  }
  lines.push(`refresh も切れていたとき: ${deadMessage}`);
  lines.push(`そのとき認可サーバーを呼んでいない: ${dead.refreshCount === 0}`);
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q7-token-client"))) {
  for (const line of await runConcurrencyDrill()) console.log(line);
}
