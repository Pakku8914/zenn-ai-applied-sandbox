import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Product } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { exposeCalls } from '../browser';
import { createFakeApi, isAbortError } from '../fakeApi';
import { KeywordInput, ProductPreview, Shell } from '../parts';
import { toError, type RequestState } from '../requestState';

const api = createFakeApi();
exposeCalls(api.calls);

type SearchResult = { keyword: string; items: Product[] };

// Good：キーワードが変わったら前の取得を中断する。中断された取得は state に触れない
function SearchGood() {
  const [keyword, setKeyword] = useState('');
  const [state, setState] = useState<RequestState<SearchResult>>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    api.searchProducts(keyword, controller.signal).then(
      (items) => setState({ status: 'success', data: { keyword, items } }),
      (error: unknown) => {
        if (isAbortError(error)) return; // 自分で中断したものはエラーではない
        setState({ status: 'error', error: toError(error) });
      },
    );
    return () => controller.abort(); // 次の effect の前（キーワードが変わったとき）に呼ばれる
  }, [keyword]);

  return (
    <>
      <KeywordInput value={keyword} onChange={setKeyword} />
      {state.status === 'success' && <ProductPreview keyword={state.data.keyword} items={state.data.items} />}
      {state.status === 'loading' && <p>読み込み中…</p>}
      {state.status === 'error' && <p role="alert">読み込めませんでした（{state.error.message}）</p>}
    </>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Shell title="商品検索（中断で競合を防ぐ Good 版）">
      <SearchGood />
    </Shell>
  </StrictMode>,
);
reportWebVitals();
