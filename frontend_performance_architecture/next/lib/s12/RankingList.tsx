import type { Product } from './products';

export function RankingList({ items }: { items: readonly Product[] }) {
  return (
    <section id="ranking">
      <h2>人気ランキング</h2>
      <ol>
        {items.map((p) => (
          <li key={p.id}>
            {p.name}（{p.price} 円）
          </li>
        ))}
      </ol>
    </section>
  );
}
