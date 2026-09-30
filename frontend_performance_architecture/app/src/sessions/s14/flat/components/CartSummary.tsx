import { countOf, type CartLine } from '../utils/cart';
import { formatCartTotal } from '../utils/format';

export function CartSummary({ lines }: { lines: readonly CartLine[] }) {
  return (
    <aside aria-label="カート" style={{ margin: '16px 0', padding: 8, background: '#f5f5f5' }}>
      カート：{countOf(lines)} 点／合計 {formatCartTotal(lines)}
    </aside>
  );
}
