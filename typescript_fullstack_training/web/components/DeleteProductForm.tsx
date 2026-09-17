'use client';

// 商品を削除するフォーム（最終プロジェクト）。
//
// 削除はやり直せない操作なので、送信の前に確認を挟む。ただし
// confirm を外されても困らないように、注文実績のある商品は
// サーバー側（外部キー制約）が最後に守っている。

import { useActionState } from 'react';
import { deleteProductAction } from '@/lib/admin-product-actions';
import type { CartActionState } from '@/lib/validation';

const INITIAL_STATE: CartActionState = { kind: 'idle' };

type DeleteProductFormProps = {
  productId: number;
  productName: string;
};

export function DeleteProductForm({ productId, productName }: DeleteProductFormProps) {
  const [state, formAction, isPending] = useActionState(deleteProductAction, INITIAL_STATE);

  return (
    <form
      action={formAction}
      onSubmit={(event) => {
        if (!window.confirm(`${productName}を削除します。よろしいですか？`)) {
          event.preventDefault();
        }
      }}
    >
      <input type="hidden" name="productId" value={productId} />
      <button type="submit" disabled={isPending}>
        {isPending ? '削除中…' : '削除'}
      </button>
      {state.kind === 'error' ? <span role="alert">{state.messages.join(' / ')}</span> : null}
    </form>
  );
}
