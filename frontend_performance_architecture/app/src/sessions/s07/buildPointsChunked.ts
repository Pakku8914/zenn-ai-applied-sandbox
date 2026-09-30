import { ROWS, computeRow } from './points';
import { yieldToMain } from './yieldToMain';

/** 1 回のスライスで使ってよい時間。フレーム予算 16.7ms の半分に抑え、描画と入力の分を残す。 */
export const DEFAULT_BUDGET_MS = 8;

export type ChunkedOptions = {
  budgetMs?: number;
  signal?: AbortSignal;
  onProgress?: (doneRows: number) => void;
};

export type ChunkedResult = { points: number[]; chunks: number };

/**
 * buildPointsSync() と同じ点列を、budgetMs ごとにメインスレッドを譲りながら計算する。
 * 回数ではなく経過時間で区切るので、端末の速さが違っても 1 スライスの長さがそろう。
 */
export async function buildPointsChunked(options: ChunkedOptions = {}): Promise<ChunkedResult> {
  const { budgetMs = DEFAULT_BUDGET_MS, signal, onProgress } = options;
  signal?.throwIfAborted();

  const points: number[] = [];
  let chunks = 1;
  let sliceStart = performance.now();

  for (let i = 0; i < ROWS; i += 1) {
    points.push(computeRow(i));

    const isLast = i === ROWS - 1;
    if (!isLast && performance.now() - sliceStart >= budgetMs) {
      onProgress?.(i + 1);
      await yieldToMain();
      // 譲っている間にグラフが隠された（中断された）なら、続きを計算しない
      signal?.throwIfAborted();
      chunks += 1;
      sliceStart = performance.now();
    }
  }
  return { points, chunks };
}
