import { products } from '../../data/products';
import { BUCKET_SIZE, priceBuckets } from './priceBuckets';

const WIDTH = 600;
const HEIGHT = 160;

/**
 * 価格帯の分布を棒グラフで描く。出発点の HeavyChart と違い、重い同期計算はしない。
 * 「グラフを表示」ボタンを押したときだけ描画される。
 */
export function PriceChart() {
  const counts = priceBuckets(products);
  const max = Math.max(...counts);
  const barWidth = WIDTH / counts.length;

  return (
    <figure data-chart="price" style={{ margin: '16px 0' }}>
      <svg width={WIDTH} height={HEIGHT} role="img" aria-label="価格帯ごとの商品数">
        {counts.map((count, i) => {
          const h = Math.round((count / max) * (HEIGHT - 10));
          return (
            <rect
              key={i}
              x={i * barWidth + 4}
              y={HEIGHT - h}
              width={barWidth - 8}
              height={h}
              fill="#3178c6"
            />
          );
        })}
      </svg>
      <figcaption>
        価格帯ごとの商品数（{BUCKET_SIZE.toLocaleString('ja-JP')} 円刻み・全 {products.length.toLocaleString('ja-JP')} 件）
      </figcaption>
    </figure>
  );
}
