import { useEffect, useState } from 'react';
import { ChartFigure } from '../ChartFigure';
import type { PointsRequest, PointsResponse } from './protocol';

/** 改善案 (b)：計算を Web Worker（別スレッド）に移し、メインスレッドは結果を受け取って描くだけにする。 */
export function WorkerChart() {
  const [points, setPoints] = useState<number[] | null>(null);
  const [error, setError] = useState<string>();

  useEffect(() => {
    // new URL(..., import.meta.url) を new Worker の中に直接書くと、Vite が Worker 用に別ビルドする
    const worker = new Worker(new URL('./points.worker.ts', import.meta.url), { type: 'module' });

    worker.addEventListener('message', (event: MessageEvent<PointsResponse>) => {
      setPoints(event.data.points);
    });
    worker.addEventListener('error', (event) => {
      setError(event.message || 'Worker を起動できませんでした');
    });

    const request: PointsRequest = { kind: 'build' };
    worker.postMessage(request);

    // グラフを隠したら Worker ごと止める（計算の途中でも破棄できる）
    return () => worker.terminate();
  }, []);

  return <ChartFigure points={points} pendingLabel="グラフを計算中…（別スレッドで計算しています）" error={error} />;
}
