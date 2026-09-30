import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Product } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { exposeCalls } from '../browser';
import { createQueryCache } from '../cache';
import { createFakeApi } from '../fakeApi';
import { KeywordInput, ProductPreview, Shell } from '../parts';
import { useQuery } from '../useQuery';

const api = createFakeApi();
exposeCalls(api.calls);

// 取得・キャッシュ・再検証・失効を分けた版。30 秒は新鮮、5 分までは古くても見せて裏で確認、それ以降は失効
const searchCache = createQueryCache<Product[]>({
  fetcher: (keyword) => api.searchProducts(keyword),
  staleMs: 30_000,
  expireMs: 300_000,
});

function CachedSearch() {
  const [keyword, setKeyword] = useState('');
  const state = useQuery(searchCache, keyword);

  return (
    <>
      <KeywordInput value={keyword} onChange={setKeyword} />
      {state.status === 'loading' && <p>読み込み中…</p>}
      {state.status === 'error' && <p role="alert">読み込めませんでした（{state.error.message}）</p>}
      {state.status === 'success' && (
        <ProductPreview keyword={keyword} items={state.data} note={state.revalidating ? '更新を確認中' : undefined} />
      )}
    </>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Shell title="商品検索（キャッシュと再検証の版）">
      <CachedSearch />
    </Shell>
  </StrictMode>,
);
reportWebVitals();
