import { useEffect, useState, type CSSProperties } from 'react';
import type { Product } from '../../data/products';
import { makeProducts } from '../s08/makeProducts';
import { ROW_HEIGHT, VIEWPORT_HEIGHT, pageStyle, rowStyle, viewportStyle } from './rows';
import { VirtualProductList } from './VirtualProductList';

/**
 * S11：一覧が少し遅れて届く画面で、待っている間の表示（スケルトン）と CLS の関係を比べる。
 *   none     … Bad。届くまで何も描かない。届いた瞬間に一覧が現れ、下の「最近チェックした商品」を押し下げる
 *   mismatch … Bad。灰色の棒を 3 本だけ置く。本物（表示枠 400px）より低いので、やはり押し下げる
 *   fixed    … Good。本物と同じ表示枠・同じ行の高さでスケルトンを作る。届いても周りは動かない
 */
export type SkeletonMode = 'none' | 'mismatch' | 'fixed';

/** 一覧が届くまでの時間（擬似）。measure/src/session11/verify-skeleton.ts はこれより長く待ってから CLS を読む */
export const LOAD_DELAY_MS = 800;

const MODE_LABEL: Record<SkeletonMode, string> = { none: 'スケルトンなし', mismatch: '高さ違い', fixed: '高さ一致' };

const barStyle: CSSProperties = { height: 16, margin: '12px 8px', borderRadius: 4, background: '#e5e7eb' };

function useDelayedProducts(): readonly Product[] | null {
  const [items, setItems] = useState<readonly Product[] | null>(null);
  useEffect(() => {
    const id = setTimeout(() => setItems(makeProducts(2000)), LOAD_DELAY_MS);
    return () => clearTimeout(id);
  }, []);
  return items;
}

function ListSkeleton({ mode }: { mode: 'mismatch' | 'fixed' }) {
  if (mode === 'mismatch') {
    // それらしく見えるが、高さは約 100px。本物の枠（400px）との差だけ下が押し下げられる
    return (
      <section>
        <h2>商品一覧（読み込み中）</h2>
        <div aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} style={barStyle} />
          ))}
        </div>
      </section>
    );
  }
  // 本物と同じ viewportStyle（高さ 400px）と rowStyle（高さ 40px）から作るので、高さが必ず一致する
  return (
    <section>
      <h2>商品一覧（読み込み中）</h2>
      <div aria-busy="true" style={{ ...viewportStyle, overflowY: 'hidden' }}>
        {Array.from({ length: VIEWPORT_HEIGHT / ROW_HEIGHT }, (_, i) => (
          <div key={i} style={{ ...rowStyle, padding: '0 8px' }}>
            <div style={{ ...barStyle, margin: 0, width: '60%' }} />
          </div>
        ))}
      </div>
    </section>
  );
}

export function SkeletonCatalog({ mode }: { mode: SkeletonMode }) {
  const items = useDelayedProducts();

  return (
    <main style={pageStyle}>
      <h1>商品カタログ（{MODE_LABEL[mode]}）</h1>

      {items !== null ? (
        <div data-list="loaded">
          <VirtualProductList items={items} />
        </div>
      ) : mode === 'none' ? null : (
        <div data-list="loading">
          <ListSkeleton mode={mode} />
        </div>
      )}

      <aside style={{ boxSizing: 'border-box', height: 200, marginTop: 16, padding: 16, borderRadius: 8, background: '#eef2ff' }}>
        <h3 style={{ margin: 0 }}>最近チェックした商品</h3>
        <p>商品12・商品345・商品1024</p>
      </aside>
    </main>
  );
}
