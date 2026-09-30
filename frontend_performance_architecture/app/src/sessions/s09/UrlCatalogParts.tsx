import { products } from '../../data/products';
import { CATEGORY_OPTIONS, MAX_KEYWORD_LENGTH, filterProducts, toCategory } from './catalogQuery';
import { countRender } from './renderCount';
import { ResultList } from './ResultList';
import { endTyping, updateCatalog, useCatalogSelector } from './urlState';

/** キーワード入力。値の持ち主は URL で、この部品は読むだけ */
export function UrlSearchBox() {
  countRender('SearchBox');
  const keyword = useCatalogSelector((q) => q.keyword);
  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        maxLength={MAX_KEYWORD_LENGTH}
        placeholder="例: 商品1"
        onChange={(e) => updateCatalog({ keyword: e.target.value }, 'typing')}
        onBlur={endTyping}
        onKeyDown={(e) => {
          if (e.key === 'Enter') endTyping();
        }}
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />
    </>
  );
}

/** カテゴリの選択。選ぶ操作は1回で確定するので、毎回履歴に積む */
export function UrlCategoryFilter() {
  countRender('CategoryFilter');
  const category = useCatalogSelector((q) => q.category);
  return (
    <>
      <label htmlFor="category">カテゴリ</label>
      <select
        id="category"
        value={category}
        onChange={(e) => updateCatalog({ category: toCategory(e.target.value) }, 'commit')}
        style={{ display: 'block', padding: 8, marginBottom: 16 }}
      >
        {CATEGORY_OPTIONS.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </>
  );
}

/** 絞り込み結果。件数も一覧も URL から毎回計算し、state に写さない */
export function UrlResults({ onAdd }: { onAdd?: (id: number) => void }) {
  countRender('CatalogResults');
  // オブジェクトを丸ごと選ぶと毎回新しい参照になるので、プリミティブを1つずつ選ぶ
  const keyword = useCatalogSelector((q) => q.keyword);
  const category = useCatalogSelector((q) => q.category);
  const items = filterProducts(products, { keyword, category });
  return <ResultList items={items} onAdd={onAdd} />;
}
