import type { Product } from '../../../../../data/products';
import { useCatalogSelector } from '../../../../s09/urlState';
import { useDebouncedValue } from '../../../../s16/useDebouncedValue';
import { mutedTextStyle, statusStyle } from '../../shared/ui/styles';
import { CatalogList } from './CatalogList';
import { LIVE_DELAY_MS, countHeading, filterByKeyword, statusMessage } from './catalogView';

/** catalog の外（app）との契約。ここに無いものを app は渡せないし、catalog は受け取れない */
export type CatalogProps = {
  /** 全商品。どこから来たか（生成・API・キャッシュ）は app が決める */
  items: readonly Product[];
  /** 商品が選ばれたとき。選ばれた商品を何に使うか（印刷など）も app が決める */
  onSelect: (product: Product) => void;
};

/** 絞り込み結果の見出し・件数の読み上げ・仮想化した一覧。キーワードは URL から読む（props で受け取らない） */
export function Catalog({ items, onSelect }: CatalogProps) {
  const keyword = useCatalogSelector((q) => q.keyword);
  const filtered = filterByKeyword(items, keyword);
  // 見出しの件数はすぐ変え、読み上げは打ち終わってから 1 回だけにする（S16）
  const announced = useDebouncedValue(statusMessage(filtered.length, items.length, keyword), LIVE_DELAY_MS);

  return (
    <section aria-labelledby="list-heading">
      <h2 id="list-heading">{countHeading(filtered.length)}</h2>
      {/* ライブリージョンは最初から DOM に置き、中身だけを書き換える */}
      <p role="status" style={statusStyle}>
        {announced}
      </p>
      <p id="select-hint" style={mutedTextStyle}>
        商品名を押すと印刷用 HTML を作ります。一覧の中は ↑↓・Home・End で移動できます。
      </p>
      {filtered.length > 0 ? (
        // 絞り込み条件が変わったら一覧を作り直し、スクロール位置と「いまの行」を先頭に戻す
        <CatalogList key={keyword} items={filtered} onSelect={onSelect} describedBy="select-hint" />
      ) : (
        <p>該当する商品はありません。</p>
      )}
    </section>
  );
}
