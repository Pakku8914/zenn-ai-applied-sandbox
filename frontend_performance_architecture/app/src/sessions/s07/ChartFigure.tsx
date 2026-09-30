import { toPolyline } from './points';

type Props = {
  points: readonly number[] | null;
  pendingLabel: string;
  error?: string;
  chunks?: number;
  yieldStrategy?: string;
};

/**
 * グラフの見た目。計算が終わる前から同じ大きさの枠を描いておき（CLS を起こさない）、
 * 「計算中」の表示を先に返す。data-state は検証スクリプトが状態の移り変わりを読むための目印。
 */
export function ChartFigure({ points, pendingLabel, error, chunks, yieldStrategy }: Props) {
  const state = error !== undefined ? 'error' : points !== null ? 'ready' : 'pending';

  return (
    <figure
      style={{ margin: '16px 0' }}
      data-state={state}
      data-chunks={chunks}
      data-yield={yieldStrategy}
      aria-busy={state === 'pending'}
    >
      <svg width={600} height={160} role="img" aria-label="売上推移">
        {points !== null && state === 'ready' ? (
          <polyline fill="none" stroke="#3178c6" strokeWidth={2} points={toPolyline(points)} />
        ) : (
          <text x={300} y={84} textAnchor="middle" fill={state === 'error' ? '#b91c1c' : '#6b7280'}>
            {state === 'error' ? `グラフを表示できませんでした（${error}）` : pendingLabel}
          </text>
        )}
      </svg>
      <figcaption>直近 100 日の推移（計測用のダミーデータ）</figcaption>
    </figure>
  );
}
