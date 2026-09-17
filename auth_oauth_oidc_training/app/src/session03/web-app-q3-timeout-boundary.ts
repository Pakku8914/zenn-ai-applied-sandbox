// 問題 3 の解答: アイドル期限と絶対期限の境界を、注入した時計で確かめます。
// 実行: docker compose exec app npx tsx src/session03/web-app-q3-timeout-boundary.ts
import { pathToFileURL } from "node:url";
import { SessionStore } from "./web-app-session-store.js";

export type BoundaryResult = {
  /** 無操作がちょうど 2000ms のとき、セッションは生きているか */
  readonly atIdleLimit: boolean;
  /** 無操作が 2001ms のとき、セッションは生きているか */
  readonly justOverIdleLimit: boolean;
  /** 1500ms ごとに触り続けたとき、4500ms 時点で生きているか */
  readonly aliveWhileTouched: boolean;
  /** 触り続けても絶対期限（5000ms）を超えたら生きているか */
  readonly aliveAfterAbsoluteLimit: boolean;
};

// 期限の短いストアと、時刻を自由に動かせる時計をセットで作る
function makeStore(): { store: SessionStore; at: (time: number) => void } {
  let clock = 0;
  const store = new SessionStore({
    idleTimeoutMs: 2000,
    absoluteTimeoutMs: 5000,
    now: () => clock,
  });
  return {
    store,
    at: (time) => {
      clock = time;
    },
  };
}

export function probeTimeouts(): BoundaryResult {
  // (1) 無操作がちょうど 2000ms
  const first = makeStore();
  const s1 = first.store.create("alice");
  first.at(2000);
  const atIdleLimit = first.store.get(s1.id) !== undefined;

  // (2) 無操作が 2001ms
  const second = makeStore();
  const s2 = second.store.create("alice");
  second.at(2001);
  const justOverIdleLimit = second.store.get(s2.id) !== undefined;

  // (3) 1500ms ごとに触り続ける（アイドル期限は毎回リセットされる）
  const third = makeStore();
  const s3 = third.store.create("alice");
  for (const time of [1500, 3000, 4500]) {
    third.at(time);
    third.store.get(s3.id);
  }
  const aliveWhileTouched = third.store.get(s3.id) !== undefined;

  // (4) 触り続けても発行から 5000ms を超えたら切れる
  const fourth = makeStore();
  const s4 = fourth.store.create("alice");
  for (const time of [1500, 3000, 4500, 6000]) {
    fourth.at(time);
    fourth.store.get(s4.id);
  }
  const aliveAfterAbsoluteLimit = fourth.store.get(s4.id) !== undefined;

  return { atIdleLimit, justOverIdleLimit, aliveWhileTouched, aliveAfterAbsoluteLimit };
}

function main(): void {
  const result = probeTimeouts();
  console.log("=== 有効期限の境界 ===");
  console.log(`無操作ちょうど 2000ms : ${result.atIdleLimit}`);
  console.log(`無操作 2001ms : ${result.justOverIdleLimit}`);
  console.log(`1500ms ごとに触って 4500ms 時点 : ${result.aliveWhileTouched}`);
  console.log(`触り続けて 6000ms 時点（絶対期限超え） : ${result.aliveAfterAbsoluteLimit}`);
}

const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  main();
}
