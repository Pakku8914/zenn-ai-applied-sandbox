import { createContext, useContext, useState, type ReactNode } from 'react';
import { products } from '../../../data/products';
import {
  CATEGORY_ALL,
  CATEGORY_OPTIONS,
  countInCategory,
  filterProducts,
  toCategory,
  type CategoryOption,
} from '../catalogQuery';
import { countRender } from '../renderCount';
import { ResultList } from '../ResultList';

/** Bad：画面の状態をすべて1つの Context に入れている */
type CatalogValue = {
  keyword: string;
  setKeyword: (value: string) => void;
  category: CategoryOption;
  setCategory: (value: CategoryOption) => void;
  cartIds: readonly number[];
  addToCart: (id: number) => void;
};

const CatalogContext = createContext<CatalogValue | null>(null);

function useCatalog(): CatalogValue {
  const value = useContext(CatalogContext);
  if (value === null) {
    throw new Error('useCatalog は CatalogProvider の内側で使ってください');
  }
  return value;
}

export function CatalogProvider({ children }: { children: ReactNode }) {
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<CategoryOption>(CATEGORY_ALL);
  const [cartIds, setCartIds] = useState<readonly number[]>([]);
  const addToCart = (id: number) => setCartIds((ids) => [...ids, id]);

  // どれか1つが変わるたびに新しいオブジェクトになり、読んでいる部品がすべて再レンダリングされる
  return (
    <CatalogContext value={{ keyword, setKeyword, category, setCategory, cartIds, addToCart }}>
      {children}
    </CatalogContext>
  );
}

export function SearchBox() {
  countRender('SearchBox');
  const { keyword, setKeyword } = useCatalog();
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
    </>
  );
}

export function CategoryFilter() {
  countRender('CategoryFilter');
  const { category, setCategory } = useCatalog();
  return (
    <select id="category" value={category} onChange={(e) => setCategory(toCategory(e.target.value))}>
      {CATEGORY_OPTIONS.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

export function CartBadge() {
  countRender('CartBadge');
  const { cartIds } = useCatalog();
  return <p id="cart-count">カート：{cartIds.length} 点</p>;
}

export function CartBookBadge() {
  countRender('CartBookBadge');
  const { cartIds } = useCatalog();
  return <p id="cart-books">うち書籍：{countInCategory(cartIds, '書籍', products)} 点</p>;
}

export function CatalogResults() {
  countRender('CatalogResults');
  const { keyword, category, addToCart } = useCatalog();
  return <ResultList items={filterProducts(products, { keyword, category })} onAdd={addToCart} />;
}
