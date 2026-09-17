'use client';

// カート明細の数量を変更するフォーム（練習問題1）。
// AddToCartForm と同じ形。違うのは送信先の Server Action と初期値だけ。

import { useActionState } from 'react';
import { changeQuantityAction } from '@/lib/cart-actions';
import { buildQuantityOptions } from '@/lib/cart';
import type { CartActionState } from '@/lib/validation';

const INITIAL_STATE: CartActionState = { kind: 'idle' };

type QuantityFormProps = {
  productId: number;
  quantity: number;
  stock: number;
};

export function QuantityForm({ productId, quantity, stock }: QuantityFormProps) {
  const [state, formAction, isPending] = useActionState(changeQuantityAction, INITIAL_STATE);

  return (
    <form action={formAction}>
      <input type="hidden" name="productId" value={productId} />
      <label>
        {'数量 '}
        {/* 選択肢は在庫と上限の小さいほうまで。画面に 10 を直接書かない */}
        <select name="quantity" defaultValue={quantity} required>
          {buildQuantityOptions(stock).map((option) => (
            <option key={option} value={option}>
              {`${option}点`}
            </option>
          ))}
        </select>
      </label>{' '}
      <button type="submit" disabled={isPending}>
        {isPending ? '変更中…' : '数量を変更'}
      </button>
      {state.kind === 'error' ? (
        <ul>
          {state.messages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}
