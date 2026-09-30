import type { Product } from '../../../data/products';

/** 純粋関数：指定価格以下の商品を安い順に返す。元の配列は並べ替えない */
export function selectCheap(items: readonly Product[], maxPrice: number): Product[] {
  return items.filter((p) => p.price <= maxPrice).toSorted((a, b) => a.price - b.price || a.id - b.id);
}

type ViewProps = {
  maxPrice: number;
  items: readonly Product[];
};

/** 表示専用：受け取った商品をそのまま描く */
export function CheapProductsView({ maxPrice, items }: ViewProps) {
  return (
    <section>
      <h2>
        {maxPrice} 円以下の商品（{items.length} 件）
      </h2>
      <ol>
        {items.map((p) => (
          <li key={p.id}>
            {p.name}：{p.price} 円
          </li>
        ))}
      </ol>
    </section>
  );
}

/** 組み立て役：どの商品を渡すかだけを決める。データの出どころは呼び出し側が決める */
export function CheapProducts({ items, maxPrice }: { items: readonly Product[]; maxPrice: number }) {
  return <CheapProductsView maxPrice={maxPrice} items={selectCheap(items, maxPrice)} />;
}
