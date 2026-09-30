import { useState } from 'react';
import { ProductList } from '../../../components/ProductList';
import { products, type Product } from '../../../data/products';

export type RenderCard = (product: Product) => string;

type Props = {
  /** 印刷用 HTML を作る関数を用意する。静的 import か動的 import() かはページ側が決める */
  loadRenderer: () => Promise<RenderCard>;
};

/**
 * 商品カタログ＋「印刷用 HTML を作る」ボタン。S05 の印刷系ページで共通の画面。
 * ページごとに違うのは loadRenderer の中身（どう読み込むか）だけにしてある。
 */
export function PrintCatalog({ loadRenderer }: Props) {
  const [html, setHtml] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');

  const handleClick = async (): Promise<void> => {
    setStatus('loading');
    try {
      const render = await loadRenderer();
      setHtml(products.slice(0, 3).map(render).join('\n'));
      setStatus('idle');
    } catch {
      // 動的 import はネットワーク越しの取得なので失敗しうる。黙って固まらせない
      setStatus('error');
    }
  };

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（計測用）</h1>

      <button id="print-button" type="button" onClick={handleClick} disabled={status === 'loading'}>
        印刷用 HTML を作る
      </button>
      {status === 'error' ? (
        <p role="alert">印刷機能の読み込みに失敗しました。通信状態を確認して、もう一度押してください。</p>
      ) : null}
      <pre id="print-output" style={{ whiteSpace: 'pre-wrap' }}>
        {html}
      </pre>

      <ProductList keyword="" />
    </main>
  );
}
