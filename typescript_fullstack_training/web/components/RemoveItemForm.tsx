'use client';

// 明細を削除するフォーム（セッション24）。
// 入力欄は隠しフィールド1つだけ。それでも「フォーム」にするのは、
// 削除がサーバーの状態を変える操作（POST）だからである。

import { useActionState } from 'react';
import { removeItemAction } from '@/lib/cart-actions';
import type { CartActionState } from '@/lib/validation';

const INITIAL_STATE: CartActionState = { kind: 'idle' };

type RemoveItemFormProps = {
  productId: number;
};

export function RemoveItemForm({ productId }: RemoveItemFormProps) {
  const [state, formAction, isPending] = useActionState(removeItemAction, INITIAL_STATE);

  return (
    <form action={formAction}>
      <input type="hidden" name="productId" value={productId} />
      <button type="submit" disabled={isPending}>
        {isPending ? '削除中…' : '削除'}
      </button>
      {state.kind === 'error' ? <span>{state.messages.join(' / ')}</span> : null}
    </form>
  );
}
