import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Product } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { exposeCalls, markDone } from '../browser';
import { createFakeApi } from '../fakeApi';
import { ProductPreview, Shell } from '../parts';

const api = createFakeApi();
exposeCalls(api.calls);

// Bad：各部品が「自分が描画されてから」取得を始める。子は親のデータが届くまで描画されないので直列になる
function CatalogPage() {
  const [categories, setCategories] = useState<string[] | null>(null);
  useEffect(() => {
    api.getCategories().then(setCategories);
  }, []);
  if (categories === null) return <p>カテゴリを読み込み中…</p>;
  return (
    <>
      <p id="categories">カテゴリ：{categories.join('・')}</p>
      <ProductSection />
    </>
  );
}

function ProductSection() {
  const [items, setItems] = useState<Product[] | null>(null);
  useEffect(() => {
    api.getProducts().then(setItems);
  }, []);
  if (items === null) return <p>商品を読み込み中…</p>;
  return (
    <>
      <ProductPreview keyword="" items={items} />
      <RankingSection />
    </>
  );
}

function RankingSection() {
  const [ranking, setRanking] = useState<Product[] | null>(null);
  useEffect(() => {
    api.getRanking().then(setRanking);
  }, []);
  useEffect(() => {
    if (ranking !== null) markDone();
  }, [ranking]);
  if (ranking === null) return <p>ランキングを読み込み中…</p>;
  return <p id="ranking">高額ランキング：{ranking.map((p) => p.name).join('・')}</p>;
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Shell title="商品カタログ（直列取得の Bad 版）">
      <CatalogPage />
    </Shell>
  </StrictMode>,
);
reportWebVitals();
