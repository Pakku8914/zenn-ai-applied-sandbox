import type { ReactNode } from 'react';

type Props = {
  title: string;
  keyword: string;
  onKeywordChange: (value: string) => void;
  children: ReactNode;
};

/** 見出しと #keyword の入力欄。出発点の App と同じ見た目・同じセレクタにしてある */
export function CatalogFrame({ title, keyword, onKeywordChange, children }: Props) {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>{title}</h1>

      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => onKeywordChange(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />

      {children}
    </main>
  );
}
