/**
 * 描画前に同期的な重い計算を行うコンポーネント。
 * メインスレッドを塞ぐので、表示ボタンを押したときの応答（INP）が悪化する。
 * 遅延読み込み・Web Worker・useDeferredValue の題材として使う。
 */
export function HeavyChart() {
  const points = buildPoints();

  return (
    <figure style={{ margin: '16px 0' }}>
      <svg width={600} height={160} role="img" aria-label="売上推移">
        <polyline
          fill="none"
          stroke="#3178c6"
          strokeWidth={2}
          points={points.map((y, x) => `${x * 6},${160 - y}`).join(' ')}
        />
      </svg>
      <figcaption>直近 100 日の推移（計測用のダミーデータ）</figcaption>
    </figure>
  );
}

/** 意図的に重い同期計算（約 150〜250ms）。乱数を使わないので結果は毎回同じ。 */
function buildPoints(): number[] {
  const result: number[] = [];
  for (let i = 0; i < 100; i += 1) {
    let acc = 0;
    for (let j = 0; j < 200_000; j += 1) {
      acc = (acc + (i * j) % 97) % 150;
    }
    result.push(acc);
  }
  return result;
}
