import { useCallback, useState, useTransition } from 'react';
import type { Product } from '../../data/products';
import { CatalogFrame } from './CatalogFrame';
import { MemoProductList } from './MemoProductList';
import { countRender } from './renderCount';

type Props = { title: string; products: readonly Product[] };

/**
 * useTransition 版：state を2つに分け、入力欄の文字（text）は急ぎで、
 * 一覧の絞り込み条件（keyword）は startTransition の中で更新する。
 * 自分で setState を呼べる場所なら、こちらの書き方も選べる。
 */
export function CatalogTransition({ title, products }: Props) {
  countRender('catalog');
  const [text, setText] = useState('');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isPending, startTransition] = useTransition();
  const handleSelect = useCallback((id: number) => setSelectedId(id), []);

  const handleChange = (value: string) => {
    setText(value);
    startTransition(() => setKeyword(value));
  };

  return (
    <CatalogFrame title={title} keyword={text} onKeywordChange={handleChange}>
      <div style={{ opacity: isPending ? 0.6 : 1 }}>
        <MemoProductList products={products} keyword={keyword} selectedId={selectedId} onSelect={handleSelect} />
      </div>
    </CatalogFrame>
  );
}
