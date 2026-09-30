import type { Product } from '../../../data/products';

/**
 * 問題5 の出発点：表示部品が URL を直接読み、通信も自分で行っている。
 * 描画中に window を読むので、window の無い環境（vitest・SSR）では描画できない。
 */
export function ProductRowBad({ product }: { product: Product }) {
  const keyword = new URLSearchParams(window.location.search).get('q') ?? '';
  const highlighted = keyword !== '' && product.name.includes(keyword);
  const handleAdd = () => {
    void fetch('/api/cart', { method: 'POST', body: JSON.stringify({ productId: product.id }) });
  };
  return (
    <li>
      <span>{highlighted ? <mark>{product.name}</mark> : product.name}</span>
      <button type="button" onClick={handleAdd}>
        カートに入れる
      </button>
    </li>
  );
}
