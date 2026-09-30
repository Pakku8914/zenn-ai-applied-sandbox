import { useState } from 'react';
import { ProductList } from '../../../components/ProductList';
import { ChartSection } from './ChartSection';

// 練習問題3の解答。ページ全体を包んでいた Suspense を外し、ChartSection の中へ移した
export function ChartPage() {
  const [show, setShow] = useState(false);
  const [keyword, setKeyword] = useState('');
  return (
    <main>
      <input id="keyword" aria-label="商品名で絞り込み" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
      <button type="button" onClick={() => setShow(true)}>
        グラフを表示
      </button>
      <ChartSection show={show} />
      <ProductList keyword={keyword} />
    </main>
  );
}
