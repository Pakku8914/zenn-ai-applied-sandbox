import type { ReactNode } from 'react';
import type { Product } from '../../data/products';

/** 表示は先頭 20 件だけにする（本章の主題は取得。大量描画は「セッション11」で扱う） */
const PREVIEW_LIMIT = 20;

export function Shell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>{title}</h1>
      {children}
    </main>
  );
}

export function KeywordInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={value}
        maxLength={100}
        placeholder="例: 商品1"
        onChange={(e) => onChange(e.target.value)}
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />
    </>
  );
}

/** どのキーワードの結果かを必ず表示する。競合状態が起きると、ここが入力欄と食い違う */
export function ProductPreview({ keyword, items, note }: { keyword: string; items: readonly Product[]; note?: string }) {
  return (
    <section>
      <p id="result-keyword">「{keyword}」の検索結果{note ? `（${note}）` : ''}</p>
      <h2>商品一覧（{items.length} 件）</h2>
      <ul>
        {items.slice(0, PREVIEW_LIMIT).map((p) => (
          <li key={p.id}>
            {p.name}（{p.category}）{p.price.toLocaleString('ja-JP')} 円
          </li>
        ))}
      </ul>
    </section>
  );
}
