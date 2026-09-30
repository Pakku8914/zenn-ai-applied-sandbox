import type { ReactNode } from 'react';
import type { Product } from '../../../data/products';
import { ProductListView } from '../catalog/ProductListView';
import { CartBadge } from './Shell';

/** 問題4 の出発点：cartCount を、使わない LayoutBad と HeaderBad が中継している（バケツリレー） */
export function CatalogShellBad({ cartCount, items }: { cartCount: number; items: readonly Product[] }) {
  return (
    <LayoutBad cartCount={cartCount}>
      <ProductListView items={items} />
    </LayoutBad>
  );
}

function LayoutBad({ cartCount, children }: { cartCount: number; children: ReactNode }) {
  return (
    <main>
      <HeaderBad cartCount={cartCount} />
      {children}
    </main>
  );
}

function HeaderBad({ cartCount }: { cartCount: number }) {
  return (
    <header>
      <h1>商品カタログ</h1>
      <CartBadge count={cartCount} />
    </header>
  );
}
