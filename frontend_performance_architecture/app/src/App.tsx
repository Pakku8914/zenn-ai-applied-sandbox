import { useState } from 'react';
import { ProductList } from './components/ProductList';
import { HeavyChart } from './components/HeavyChart';

/**
 * 計測対象のアプリ。パフォーマンスの問題を意図的に含んでいる。
 * 各セッションで、ここにある問題を1つずつ計測して直していく。
 */
export function App() {
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

      {showChart ? <HeavyChart /> : null}

      <ProductList keyword={keyword} />
    </main>
  );
}
