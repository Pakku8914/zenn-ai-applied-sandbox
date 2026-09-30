import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Product } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { exposeCalls, markDone } from '../browser';
import { createFakeApi } from '../fakeApi';
import { ProductPreview, Shell } from '../parts';
import { toError, type RequestState } from '../requestState';

const api = createFakeApi();
exposeCalls(api.calls);

type Catalog = { categories: string[]; items: Product[]; ranking: Product[] };

// Good：互いに依存しない3つの取得を、描画より前にまとめて始める
function loadCatalog(): Promise<Catalog> {
  return Promise.all([api.getCategories(), api.getProducts(), api.getRanking()]).then(
    ([categories, items, ranking]) => ({ categories, items, ranking }),
  );
}
const catalogPromise = loadCatalog(); // createRoot より前。部品の描画を待たずに通信が始まる

/** すでに始まっている取得の結果を待つだけのフック（取得は始めない） */
function usePromise<T>(promise: Promise<T>): RequestState<T> {
  const [state, setState] = useState<RequestState<T>>({ status: 'loading' });
  useEffect(() => {
    let active = true;
    promise.then(
      (data) => active && setState({ status: 'success', data }),
      (error: unknown) => active && setState({ status: 'error', error: toError(error) }),
    );
    return () => {
      active = false;
    };
  }, [promise]);
  return state;
}

function CatalogPage() {
  const state = usePromise(catalogPromise);
  useEffect(() => {
    if (state.status === 'success') markDone();
  }, [state.status]);

  if (state.status === 'loading' || state.status === 'idle') return <p>読み込み中…</p>;
  if (state.status === 'error') return <p role="alert">読み込めませんでした（{state.error.message}）</p>;
  const { categories, items, ranking } = state.data;
  return (
    <>
      <p id="categories">カテゴリ：{categories.join('・')}</p>
      <ProductPreview keyword="" items={items} />
      <p id="ranking">高額ランキング：{ranking.map((p) => p.name).join('・')}</p>
    </>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Shell title="商品カタログ（並列取得の Good 版）">
      <CatalogPage />
    </Shell>
  </StrictMode>,
);
reportWebVitals();
