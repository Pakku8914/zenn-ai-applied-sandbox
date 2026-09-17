// 練習問題 1: アクセストークンの寿命を決めるための比較表。
import { ACCESS_TOKEN_LIFESPAN, REFRESH_IDLE_TIMEOUT } from "./bookstore-tokens.js";
import { DEFAULT_SKEW_SECONDS } from "./rp-token-store.js";

/** 比較する寿命の候補（秒）: 1 分・5 分・15 分・1 時間・1 日 */
const CANDIDATES = [60, 300, 900, 3600, 86_400] as const;
/** 1 人の利用者が続けて使う時間（8 時間の勤務を想定） */
const SHIFT_SECONDS = 8 * 60 * 60;

export type LifetimeRow = {
  lifespanSeconds: number;
  /** 権限を取り消しても、最悪これだけの時間は古い権限で動けてしまう */
  maxStaleSeconds: number;
  /** 8 時間のあいだに発生するリフレッシュの回数（前倒し 30 秒を考慮） */
  refreshesPerShift: number;
};

export function buildLifetimeRows(): LifetimeRow[] {
  return CANDIDATES.map((lifespanSeconds) => {
    // 前倒しで更新するので、1 枚のトークンを実際に使える時間は少し短くなる
    const usableSeconds = lifespanSeconds - DEFAULT_SKEW_SECONDS;
    const refreshesPerShift = Math.max(0, Math.ceil(SHIFT_SECONDS / usableSeconds) - 1);
    return { lifespanSeconds, maxStaleSeconds: lifespanSeconds, refreshesPerShift };
  });
}

export function buildLifetimeTable(): string[] {
  const lines = ["=== アクセストークンの寿命の比較 ==="];
  for (const row of buildLifetimeRows()) {
    lines.push(
      `寿命 ${row.lifespanSeconds} 秒: 失効が効くまで最大 ${row.maxStaleSeconds} 秒 / ` +
        `8 時間あたりのリフレッシュ ${row.refreshesPerShift} 回`,
    );
  }
  lines.push(`本書の realm の accessTokenLifespan: ${ACCESS_TOKEN_LIFESPAN} 秒`);
  lines.push(`本書の realm の ssoSessionIdleTimeout: ${REFRESH_IDLE_TIMEOUT} 秒`);
  lines.push(
    `${ACCESS_TOKEN_LIFESPAN} 秒を選ぶ理由: 失効の遅れを 5 分に抑えつつ、` +
      "リフレッシュは 8 時間で 106 回に収まる",
  );
  lines.push("寿命を伸ばすと悪くなるもの: 失効の効き（取り消しても最大 1 日使われる）");
  lines.push("寿命を縮めると悪くなるもの: 認可サーバーへの通信量と、更新失敗の影響範囲");
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q1-lifetime-table"))) {
  for (const line of buildLifetimeTable()) console.log(line);
}
