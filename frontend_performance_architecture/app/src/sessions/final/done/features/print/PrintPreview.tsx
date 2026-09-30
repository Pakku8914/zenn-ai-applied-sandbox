import { useEffect, useState } from 'react';
import type { Product } from '../../../../../data/products';
import { loadPrintRenderer } from './loadPrintRenderer';

type Props = {
  /** 印刷する商品。まだ選ばれていなければ null */
  product: Product | null;
};

type State = { status: 'idle' } | { status: 'ready'; html: string } | { status: 'error' };

/** 選ばれた商品の印刷用 HTML を表示する。部品の読み込みは、最初に商品が選ばれたときに始まる */
export function PrintPreview({ product }: Props) {
  const [state, setState] = useState<State>({ status: 'idle' });

  useEffect(() => {
    if (product === null) return undefined;
    let cancelled = false; // 続けて別の商品が選ばれたら、古い結果で上書きしない
    loadPrintRenderer().then(
      (render) => {
        if (!cancelled) setState({ status: 'ready', html: render(product) });
      },
      () => {
        if (!cancelled) setState({ status: 'error' });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [product]);

  return (
    <>
      {state.status === 'error' ? (
        <p role="alert">印刷機能の読み込みに失敗しました。通信状態を確認して、もう一度商品名を押してください。</p>
      ) : null}
      <pre id="print-output" style={{ whiteSpace: 'pre-wrap' }}>
        {state.status === 'ready' ? state.html : ''}
      </pre>
    </>
  );
}
