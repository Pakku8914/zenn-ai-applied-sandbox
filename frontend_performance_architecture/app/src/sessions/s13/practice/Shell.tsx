import type { ReactNode } from 'react';
import type { Product } from '../../../data/products';
import { ProductListView } from '../catalog/ProductListView';

/** 再利用できる枠：何を置くかは知らない */
export function ShellLayout({ header, children }: { header: ReactNode; children: ReactNode }) {
  return (
    <main>
      {header}
      {children}
    </main>
  );
}

/** 再利用できる見出し：右側に置く操作は使う側が決める */
export function ShellHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
  );
}

/** 画面固有の部品：カートを知っている */
export function CartBadge({ count }: { count: number }) {
  return <span aria-label="カートの商品数">カート（{count}）</span>;
}

/** 組み立て役：cartCount を使う場所（CartBadge）へ直接渡す。枠と見出しは中継しない */
export function CatalogShell({ cartCount, items }: { cartCount: number; items: readonly Product[] }) {
  return (
    <ShellLayout header={<ShellHeader title="商品カタログ" actions={<CartBadge count={cartCount} />} />}>
      <ProductListView items={items} />
    </ShellLayout>
  );
}
