import type { Product } from '../../../data/products';

/** 強調するかどうかは純粋関数で決める（URL から読んだ値を受け取るだけ） */
export function isHighlighted(name: string, keyword: string): boolean {
  return keyword !== '' && name.includes(keyword);
}

type Props = {
  product: Product;
  highlighted: boolean;
  onAdd: (id: number) => void;
};

/** 表示専用：URL もストアも通信も知らない。必要な値と操作は props で受け取る */
export function ProductRow({ product, highlighted, onAdd }: Props) {
  return (
    <li>
      <span>{highlighted ? <mark>{product.name}</mark> : product.name}</span>
      <button type="button" onClick={() => onAdd(product.id)}>
        カートに入れる
      </button>
    </li>
  );
}

/** 組み立て役：外の世界（URL・通信）とつなぐのはここだけ */
export function ProductRows({
  items,
  keyword,
  addToCart,
}: {
  items: readonly Product[];
  keyword: string;
  addToCart: (id: number) => void;
}) {
  return (
    <ul>
      {items.map((p) => (
        <ProductRow key={p.id} product={p} highlighted={isHighlighted(p.name, keyword)} onAdd={addToCart} />
      ))}
    </ul>
  );
}
