import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
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

/** Good：変わる頻度で値を分け、更新関数は変わらない Context にまとめる */
type CatalogActions = {
  setKeyword: (value: string) => void;
  setCategory: (value: CategoryOption) => void;
  addToCart: (id: number) => void;
};

const KeywordContext = createContext('');
const CategoryContext = createContext<CategoryOption>(CATEGORY_ALL);
const CartContext = createContext<readonly number[]>([]);
const ActionsContext = createContext<CatalogActions | null>(null);

function useActions(): CatalogActions {
  const actions = useContext(ActionsContext);
  if (actions === null) {
    throw new Error('useActions は CatalogProvider の内側で使ってください');
  }
  return actions;
}

export function CatalogProvider({ children }: { children: ReactNode }) {
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<CategoryOption>(CATEGORY_ALL);
  const [cartIds, setCartIds] = useState<readonly number[]>([]);

  // useState の更新関数は最初から変わらないので、まとめたオブジェクトも1回だけ作れば足りる
  const actions = useMemo<CatalogActions>(
    () => ({ setKeyword, setCategory, addToCart: (id) => setCartIds((ids) => [...ids, id]) }),
    [],
  );

  return (
    <ActionsContext value={actions}>
      <KeywordContext value={keyword}>
        <CategoryContext value={category}>
          <CartContext value={cartIds}>{children}</CartContext>
        </CategoryContext>
      </KeywordContext>
    </ActionsContext>
  );
}

export function SearchBox() {
  countRender('SearchBox');
  const keyword = useContext(KeywordContext);
  const { setKeyword } = useActions();
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
  const category = useContext(CategoryContext);
  const { setCategory } = useActions();
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
  const cartIds = useContext(CartContext);
  return <p id="cart-count">カート：{cartIds.length} 点</p>;
}

export function CartBookBadge() {
  countRender('CartBookBadge');
  const cartIds = useContext(CartContext);
  return <p id="cart-books">うち書籍：{countInCategory(cartIds, '書籍', products)} 点</p>;
}

export function CatalogResults() {
  countRender('CatalogResults');
  const keyword = useContext(KeywordContext);
  const category = useContext(CategoryContext);
  const { addToCart } = useActions();
  return <ResultList items={filterProducts(products, { keyword, category })} onAdd={addToCart} />;
}
