import { useState, type ComponentType } from 'react';
import { ProductList } from '../../components/ProductList';

/**
 * 出発点の App と同じ画面。グラフの部品だけを差し替えられるようにしてある。
 * グラフ以外（入力欄・商品一覧）を出発点と同じにしておくと、差をグラフの作り方に絞れる。
 */
export function CatalogShell({ Chart }: { Chart: ComponentType }) {
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

      {showChart ? <Chart /> : null}

      <ProductList keyword={keyword} />
    </main>
  );
}
