import { useState } from 'react';
import type { Product } from '../../../data/products';
import { CATEGORY_ALL, filterProducts } from '../../s09/catalogQuery';
import { ProductListView } from './ProductListView';

type Props = {
  items: readonly Product[];
  /** 最初のキーワード（URL から復元するときなどに使う） */
  initialKeyword?: string;
};

/** 状態を持つ部品。キーワードを持ち、表示する商品を計算して表示部品へ渡す（取得はしない） */
export function ProductCatalog({ items, initialKeyword = '' }: Props) {
  const [keyword, setKeyword] = useState(initialKeyword);
  // 絞り込みは「セッション9」の純粋関数に任せる。派生状態なので state に持たない
  const visible = filterProducts(items, { keyword, category: CATEGORY_ALL });

  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />
      <ProductListView items={visible} />
    </>
  );
}
