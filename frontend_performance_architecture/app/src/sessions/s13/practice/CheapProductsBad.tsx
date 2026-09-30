import { products } from '../../../data/products';

/** 問題1 の出発点：データの読み込み・絞り込み・並べ替え・表示を1つの部品で行っている */
export function CheapProductsBad({ maxPrice }: { maxPrice: number }) {
  const cheap = products.filter((p) => p.price <= maxPrice).sort((a, b) => a.price - b.price);
  return (
    <section>
      <h2>
        {maxPrice} 円以下の商品（{cheap.length} 件）
      </h2>
      <ol>
        {cheap.map((p) => (
          <li key={p.id}>
            {p.name}：{p.price} 円
          </li>
        ))}
      </ol>
    </section>
  );
}
