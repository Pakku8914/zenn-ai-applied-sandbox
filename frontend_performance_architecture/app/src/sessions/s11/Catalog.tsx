import { useState } from 'react';
import type { Product } from '../../data/products';
import { PlainProductList } from './PlainProductList';
import { VirtualProductList } from './VirtualProductList';
import { pageStyle } from './rows';

type Props = {
  title: string;
  products: readonly Product[];
  mode: 'plain' | 'virtual';
};

/** 見出しと #keyword の入力欄（出発点と同じセレクタ）に、全件描画版か仮想化版の一覧をつなぐ */
export function Catalog({ title, products, mode }: Props) {
  const [keyword, setKeyword] = useState('');
  // 絞り込みは keyword が変わったときだけ走る。スクロール位置は一覧の中の state なので、スクロールではここは再実行されない
  const filtered = products.filter((p) => p.name.includes(keyword));
  const List = mode === 'virtual' ? VirtualProductList : PlainProductList;

  return (
    <main style={pageStyle}>
      <h1>{title}</h1>

      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />

      <List items={filtered} />
    </main>
  );
}
