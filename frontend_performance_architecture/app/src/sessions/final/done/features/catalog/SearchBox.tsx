import { MAX_KEYWORD_LENGTH } from '../../../../s09/catalogQuery';
import { endTyping, updateCatalog, useCatalogSelector } from '../../../../s09/urlState';
import { inputStyle } from '../../shared/ui/styles';

/** キーワード入力。値の持ち主は URL（?q=）で、この部品は読むだけ（S09） */
export function SearchBox() {
  const keyword = useCatalogSelector((q) => q.keyword);
  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        maxLength={MAX_KEYWORD_LENGTH}
        placeholder="例: 商品1"
        autoComplete="off"
        onChange={(e) => updateCatalog({ keyword: e.target.value }, 'typing')}
        onBlur={endTyping}
        onKeyDown={(e) => {
          if (e.key === 'Enter') endTyping();
        }}
        style={inputStyle}
      />
    </>
  );
}
