import { useEffect, useState } from 'react';
import type { Product } from '../../../data/products';
import { assertNever, type RequestState } from '../../s10/requestState';
import { loadProducts } from './loadProducts';
import { ProductCatalog } from './ProductCatalog';

type Props = {
  /** 商品一覧を取ってくる関数。戻り値は外から来る値なので unknown で受ける */
  load: () => Promise<unknown>;
};

/** データを取る部品。取得と検証だけを担い、見た目は子に任せる */
export function CatalogPage({ load }: Props) {
  const [state, setState] = useState<RequestState<Product[]>>({ status: 'loading' });

  useEffect(() => {
    let active = true; // 画面を離れたあとに届いた結果で state を書き換えない
    void loadProducts(load).then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [load]);

  return <CatalogContent state={state} />;
}

/** 取得の状態ごとに何を出すかを決める。状態の種類を足し忘れると assertNever で型エラーになる */
export function CatalogContent({ state }: { state: RequestState<Product[]> }) {
  switch (state.status) {
    case 'idle':
      return null;
    case 'loading':
      return <p>読み込み中…</p>;
    case 'error':
      return <p role="alert">商品を読み込めませんでした（{state.error.message}）</p>;
    case 'success':
      return <ProductCatalog items={state.data} />;
    default:
      return assertNever(state);
  }
}
