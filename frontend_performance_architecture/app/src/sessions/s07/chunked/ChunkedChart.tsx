import { useEffect, useState } from 'react';
import { ChartFigure } from '../ChartFigure';
import { buildPointsChunked } from '../buildPointsChunked';
import { ROWS } from '../points';
import { yieldStrategy } from '../yieldToMain';

/** 改善案 (a)：計算を小さなスライスに分け、スライスの間でメインスレッドを譲る。 */
export function ChunkedChart() {
  const [points, setPoints] = useState<number[] | null>(null);
  const [chunks, setChunks] = useState<number>();
  const [doneRows, setDoneRows] = useState(0);
  const [error, setError] = useState<string>();

  useEffect(() => {
    const controller = new AbortController();
    buildPointsChunked({ signal: controller.signal, onProgress: setDoneRows })
      .then((result) => {
        setPoints(result.points);
        setChunks(result.chunks);
      })
      .catch((reason: unknown) => {
        // グラフを隠した（アンマウントした）ことによる中断は失敗ではない
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => controller.abort();
  }, []);

  return (
    <ChartFigure
      points={points}
      pendingLabel={`グラフを計算中… ${Math.round((doneRows / ROWS) * 100)}%`}
      error={error}
      chunks={chunks}
      yieldStrategy={yieldStrategy()}
    />
  );
}
