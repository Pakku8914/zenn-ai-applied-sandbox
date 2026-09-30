import { products } from '../../../data/products';

/**
 * S15 問題2 の題材：出発点の ProductList の見た目の書き方だけを変えた版。
 * インライン style をクラス名に置き換え、件数と価格はテンプレート文字列で1つの文字列にしている。
 * 利用者に見えるもの（見出しの文言・行数・各行の文字）は ProductList と同じ。
 */
export function ProductListRestyled({ keyword }: { keyword: string }) {
  const filtered = products.filter((p) => p.name.includes(keyword));
  return (
    <section className="catalog">
      <h2 className="catalog__title">{`商品一覧（${filtered.length} 件）`}</h2>
      <ul className="catalog__list">
        {filtered.map((p) => (
          <li key={p.id} className="catalog__row">
            <span className="catalog__name">{p.name}</span>
            <span className="catalog__price">{`${p.price} 円`}</span>
            <span className="catalog__category">{p.category}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
