import { lazy, Suspense, useState } from 'react';
import { ProductList } from '../../../components/ProductList';

// React.lazy は「default に部品を持つモジュール」を返す関数を受け取る。
// HeavyChart は名前付きエクスポートなので、{ default: ... } の形に詰め替える。
// lazy はモジュールの最上位で1回だけ呼ぶ（部品の中で呼ぶと描画のたびに別の部品になる）。
const HeavyChart = lazy(() =>
  import('../../../components/HeavyChart').then((m) => ({ default: m.HeavyChart })),
);

/** 出発点の App と同じ画面。違いは HeavyChart を押したときに読み込むことだけ。 */
export function LazyChartApp() {
  const [keyword, setKeyword] = useState('');
  const [showChart, setShowChart] = useState(false);

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（計測用）</h1>

      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />

      <button type="button" onClick={() => setShowChart((v) => !v)}>
        {showChart ? 'グラフを隠す' : 'グラフを表示'}
      </button>

      {/* Suspense は遅延させる部品のすぐ外側に置く。外側すぎると一覧まで fallback に置き換わる */}
      {showChart ? (
        <Suspense fallback={<p role="status">グラフを読み込み中…</p>}>
          <HeavyChart />
        </Suspense>
      ) : null}

      <ProductList keyword={keyword} />
    </main>
  );
}
