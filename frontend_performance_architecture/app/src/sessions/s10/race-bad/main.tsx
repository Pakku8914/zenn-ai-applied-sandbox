import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Product } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { exposeCalls } from '../browser';
import { createFakeApi } from '../fakeApi';
import { KeywordInput, ProductPreview, Shell } from '../parts';

const api = createFakeApi();
exposeCalls(api.calls);

type SearchResult = { keyword: string; items: Product[] };

// Bad：届いた応答を届いた順に state へ書く。後から届いた古い応答が新しい結果を上書きする
function SearchBad() {
  const [keyword, setKeyword] = useState('');
  const [result, setResult] = useState<SearchResult | null>(null);

  useEffect(() => {
    api.searchProducts(keyword).then((items) => setResult({ keyword, items }));
  }, [keyword]);

  return (
    <>
      <KeywordInput value={keyword} onChange={setKeyword} />
      {result === null ? <p>読み込み中…</p> : <ProductPreview keyword={result.keyword} items={result.items} />}
    </>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Shell title="商品検索（競合状態の Bad 版）">
      <SearchBad />
    </Shell>
  </StrictMode>,
);
reportWebVitals();
