import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ProductList } from '../../../components/ProductList';
import { products } from '../../../data/products';
import { onceWithRetry } from './onceWithRetry';
import { reportWebVitals } from '../../../vitals';

// 練習問題4の解答。取得は1回にまとめ、失敗したら押し直しで再取得できるようにする
const loadRenderer = onceWithRetry(() =>
  import('../print/renderPrintCard').then((m) => m.renderPrintCard),
);

function PrefetchPrintCatalog() {
  const [html, setHtml] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');

  // 押されそうになった時点（ポインターが乗った・フォーカスが来た）で取得を始める。
  // 失敗してもここでは表示を変えない。本番のクリックでもう一度試みる
  const prefetch = (): void => {
    loadRenderer().catch(() => undefined);
  };

  const handleClick = async (): Promise<void> => {
    setStatus('loading');
    try {
      const render = await loadRenderer();
      setHtml(products.slice(0, 3).map(render).join('\n'));
      setStatus('idle');
    } catch {
      setStatus('error');
    }
  };

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（計測用）</h1>
      <button
        id="print-button"
        type="button"
        onPointerEnter={prefetch}
        onFocus={prefetch}
        onClick={handleClick}
        disabled={status === 'loading'}
      >
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

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <PrefetchPrintCatalog />
  </StrictMode>,
);

reportWebVitals();
