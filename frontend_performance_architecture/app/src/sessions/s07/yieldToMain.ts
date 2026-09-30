/**
 * メインスレッドをいったんブラウザに返し（入力や描画を先に処理させ）、続きを後で再開する。
 * scheduler.yield() があればそれを使い、無ければ MessageChannel、最後に setTimeout に落とす。
 */
export type YieldStrategy = 'scheduler.yield' | 'message-channel' | 'set-timeout';

type YieldingScheduler = { yield(): Promise<void> };

function findScheduler(): YieldingScheduler | undefined {
  // 型定義に scheduler が無い環境もあるため、存在を実行時に確かめてから使う
  const candidate = (globalThis as unknown as { scheduler?: { yield?: unknown } }).scheduler;
  return candidate !== undefined && typeof candidate.yield === 'function'
    ? (candidate as YieldingScheduler)
    : undefined;
}

/** この環境で yieldToMain() がどの方法を使うか。 */
export function yieldStrategy(): YieldStrategy {
  if (findScheduler()) return 'scheduler.yield';
  if (typeof MessageChannel === 'function') return 'message-channel';
  return 'set-timeout';
}

export function yieldToMain(): Promise<void> {
  const scheduler = findScheduler();
  if (scheduler) {
    // scheduler.yield() は必ず scheduler をレシーバにして呼ぶ（取り出して呼ぶと Illegal invocation）
    return scheduler.yield();
  }
  if (typeof MessageChannel === 'function') {
    // setTimeout(0) は入れ子が深くなると 4ms 以上に丸められるため、先にこちらを使う
    return new Promise((resolve) => {
      const channel = new MessageChannel();
      channel.port1.onmessage = () => {
        channel.port1.close();
        resolve();
      };
      channel.port2.postMessage(null);
    });
  }
  return new Promise((resolve) => setTimeout(resolve, 0));
}
