/**
 * 問題4：カートの数量を楽観的に増減する。
 * 表示する値 = サーバーが確定した値 + まだ応答の来ていない操作の合計。
 * 失敗した操作はリストから外すだけなので、ほかの操作の結果を巻き込まない。
 */
export function createOptimisticCounter(confirmed: number) {
  let base = confirmed;
  const pending = new Map<number, number>();
  let nextId = 1;

  return {
    /** 操作を始める。返した ID で成功・失敗を伝える */
    add(delta: number): number {
      const id = nextId;
      nextId += 1;
      pending.set(id, delta);
      return id;
    },
    confirm(id: number): void {
      const delta = pending.get(id);
      if (delta === undefined) return;
      pending.delete(id);
      base += delta;
    },
    fail(id: number): void {
      pending.delete(id);
    },
    value(): number {
      let sum = base;
      for (const delta of pending.values()) sum += delta;
      return sum;
    },
    pendingCount(): number {
      return pending.size;
    },
  };
}
