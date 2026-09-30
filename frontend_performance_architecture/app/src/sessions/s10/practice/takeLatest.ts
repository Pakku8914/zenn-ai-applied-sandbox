/** 問題3：古い呼び出しの結果であることを表す目印 */
export const SKIPPED = Symbol('skipped');

/**
 * 非同期関数を包み、最後に呼ばれたものの結果だけを返す。
 * それより前の呼び出しは、結果が届いても SKIPPED で解決する（失敗も握りつぶして SKIPPED にする）。
 */
export function takeLatest<A, R>(fn: (arg: A) => Promise<R>): (arg: A) => Promise<R | typeof SKIPPED> {
  let latestId = 0;
  return async (arg) => {
    latestId += 1;
    const id = latestId;
    try {
      const result = await fn(arg);
      return id === latestId ? result : SKIPPED;
    } catch (error) {
      if (id !== latestId) return SKIPPED;
      throw error;
    }
  };
}
