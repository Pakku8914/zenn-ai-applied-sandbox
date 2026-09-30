import { useEffect, useState } from 'react';
import { ProductList } from '../../../components/ProductList';

declare global {
  interface Window {
    /** 操作できるようになった時刻。Next.js 版の「ハイドレーション完了」と並べて比べる */
    __s12HydratedAt?: number;
  }
}

/** S12 の比較用 SPA。出発点から HeavyChart を除いた、Next.js 版と同じ画面 */
export function SpaCatalog() {
  const [keyword, setKeyword] = useState('');

  useEffect(() => {
    window.__s12HydratedAt ??= performance.now();
  }, []);

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（SPA 版）</h1>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />
      <ProductList keyword={keyword} />
    </main>
  );
}
