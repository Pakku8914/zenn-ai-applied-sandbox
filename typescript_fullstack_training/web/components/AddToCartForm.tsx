'use client';

// 「カートに入れる」フォーム（セッション24）。
//
// useActionState を使うので状態を持つ＝クライアントコンポーネントにする。
// 送信先の関数は Server Action なので、処理そのものはサーバーで動く。

import { useActionState } from 'react';
import { addToCartAction } from '@/lib/cart-actions';
import { buildQuantityOptions } from '@/lib/cart';
import type { CartActionState } from '@/lib/validation';

// CartActionState は import type で読み込んでいる。
// 型はビルド時に消えるので、validation.ts が使っている Zod がブラウザ側に混ざらない。
const INITIAL_STATE: CartActionState = { kind: 'idle' };

type AddToCartFormProps = {
  productId: number;
  productName: string;
  stock: number;
};

export function AddToCartForm({ productId, productName, stock }: AddToCartFormProps) {
  // 引数は（アクション, 初期状態）の順。戻り値は [状態, 送信先, 送信中か] の3つ
  const [state, formAction, isPending] = useActionState(addToCartAction, INITIAL_STATE);

  if (stock <= 0) {
    return <span>在庫切れ</span>;
  }

  return (
    <form action={formAction}>
      {/* サーバーに送られるのは name が付いた入力欄だけ。id は利用者に見せずに送る */}
      <input type="hidden" name="productId" value={productId} />
      <label>
        {'数量 '}
        <select name="quantity" defaultValue={1} required>
          {buildQuantityOptions(stock).map((option) => (
            <option key={option} value={option}>
              {`${option}点`}
            </option>
          ))}
        </select>
      </label>{' '}
      <button type="submit" disabled={isPending}>
        {isPending ? '追加中…' : `${productName}をカートに入れる`}
      </button>
      {state.kind === 'error' ? (
        <ul>
          {state.messages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
      {state.kind === 'ok' ? <span>{state.message}</span> : null}
    </form>
  );
}
