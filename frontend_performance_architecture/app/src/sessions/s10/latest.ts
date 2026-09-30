/**
 * リクエスト ID で「最後に始めた取得」だけを採用する。
 * 中断できない処理（中断の口がない SDK、Web Worker の計算など）の競合状態を防ぐのに使う。
 */
export function createLatestOnly() {
  let latestId = 0;
  return {
    /** 取得を始めるときに呼ぶ。返した関数は「この取得がまだ最新か」を答える */
    begin(): () => boolean {
      latestId += 1;
      const id = latestId;
      return () => id === latestId;
    },
  };
}
