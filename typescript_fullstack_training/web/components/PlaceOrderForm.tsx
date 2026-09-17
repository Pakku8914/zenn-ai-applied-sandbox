'use client';

// 「この内容で注文する」ボタン（最終プロジェクト）。
//
// isPending のあいだボタンを押せなくしているが、これは親切心（UX）であって
// 守りではない。ブラウザを2枚開かれれば2回送信できる。二重決済を本当に
// 防いでいるのは、サーバー側の冪等キーと条件付き更新である。

import { useActionState } from 'react';
import { placeOrderAction } from '@/app/checkout/actions';
import type { CartActionState } from '@/lib/validation';

const INITIAL_STATE: CartActionState = { kind: 'idle' };

type PlaceOrderFormProps = {
  /** 画面に出す支払総額。ボタンの文言に入れて「いくら払うのか」を明示する */
  payableAmountLabel: string;
};

export function PlaceOrderForm({ payableAmountLabel }: PlaceOrderFormProps) {
  const [state, formAction, isPending] = useActionState(placeOrderAction, INITIAL_STATE);

  return (
    <form action={formAction}>
      <button type="submit" disabled={isPending}>
        {isPending ? '注文を確定しています…' : `${payableAmountLabel}を支払って注文する`}
      </button>

      {state.kind === 'error' ? (
        <p role="alert">{state.messages.join(' / ')}</p>
      ) : null}
    </form>
  );
}
