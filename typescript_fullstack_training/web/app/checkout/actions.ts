'use server';

// 注文確定の Server Action（最終プロジェクト）。
//
// このファイルの役割は3つだけに絞ってある。
//   1. 誰なのかを確かめる（認証）
//   2. lib/checkout.ts の placeOrder を呼ぶ
//   3. 結果を「画面に出す状態」または「移動先」に翻訳する
//
// 業務のロジックはここに書かない。ここに書くとテストのためにフォームを
// 用意しなければならなくなるので、ロジックは lib/ の純粋な入口に置く。

import { redirect } from 'next/navigation';
import { getSessionUser } from '@/lib/session';
import { describeCheckoutFailure, placeOrder } from '@/lib/checkout';
import { errorState, type CartActionState } from '@/lib/validation';

export async function placeOrderAction(
  _prevState: CartActionState,
  _formData: FormData
): Promise<CartActionState> {
  // middleware も /checkout を守っているが、ここでも必ず確かめる（多層防御）。
  // Server Action は URL を持たないので、middleware だけでは守りきれない
  const user = await getSessionUser();

  if (user === undefined) {
    return errorState(['ログインの有効期限が切れました。ログインし直してください']);
  }

  const result = await placeOrder(user.id);

  if (result.kind === 'error') {
    return errorState([describeCheckoutFailure(result.error)]);
  }

  // 成功も保留も注文はできている。どちらも注文の詳細ページへ送り、
  // 状態（お支払い済み／お支払いの確認中）はその画面で見せる。
  // redirect は never を返す（例外を投げてページ遷移させる）ので、この後に処理は続かない
  return redirect(`/orders/${result.value.orderId}`);
}
