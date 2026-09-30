/**
 * 横断復習①：フレーム予算の計算。セッション2の考え方を関数にしたもの。
 * 描けなかったフレーム数は、セッション2のスクリプトと同じく四捨五入で数える。
 */
export const LONG_TASK_MS = 50;

/** リフレッシュレート（Hz）から、1フレームに使える時間（ms）を求める。 */
export function frameBudgetMs(hz: number): number {
  return 1000 / hz;
}

/** blockMs のあいだ画面が更新されなかったとき、描けなかったフレームの枚数。 */
export function droppedFrames(blockMs: number, hz = 60): number {
  return Math.round(blockMs / frameBudgetMs(hz));
}

/** 1回ぶんの処理（JS とブラウザ側の処理の合計）が1フレームに収まるか。 */
export function fitsInFrame(workMs: number, hz = 60): boolean {
  return workMs <= frameBudgetMs(hz);
}

/** 長いタスク（50ms 以上メインスレッドを占有する処理）か。 */
export function isLongTask(ms: number): boolean {
  return ms >= LONG_TASK_MS;
}
