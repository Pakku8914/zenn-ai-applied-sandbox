'use client';

// お届け先の入力フォーム（練習問題4）。
// エラーを「フォームの先頭にまとめて」ではなく「項目のすぐ下に」出す形。
// そのために Server Action は CustomerFieldErrors（項目ごとの配列）を返す。

import { useActionState } from 'react';
import { previewCustomerAction } from '@/lib/cart-actions';
import type { CustomerFormState } from '@/lib/validation';

const INITIAL_STATE: CustomerFormState = { kind: 'idle' };

/** 1項目分のエラーを並べる小さな部品。エラーが無いときは何も描かない */
function FieldErrors({ messages }: { messages: readonly string[] }) {
  if (messages.length === 0) {
    return null;
  }

  return (
    <ul>
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

export function CustomerForm() {
  const [state, formAction, isPending] = useActionState(previewCustomerAction, INITIAL_STATE);
  // idle のときも「エラーは空」として扱えるようにしておくと、描画側の分岐が減る
  const fieldErrors = state.kind === 'error' ? state.fieldErrors : null;

  return (
    <form action={formAction}>
      <h2>お届け先</h2>
      <FieldErrors messages={fieldErrors === null ? [] : fieldErrors.form} />

      <p>
        <label>
          {'お名前 '}
          <input type="text" name="name" maxLength={50} required />
        </label>
        <FieldErrors messages={fieldErrors === null ? [] : fieldErrors.name} />
      </p>

      <p>
        <label>
          {'メールアドレス '}
          <input type="email" name="email" required />
        </label>
        <FieldErrors messages={fieldErrors === null ? [] : fieldErrors.email} />
      </p>

      <p>
        <label>
          {'備考（任意） '}
          <textarea name="note" maxLength={200} />
        </label>
        <FieldErrors messages={fieldErrors === null ? [] : fieldErrors.note} />
      </p>

      <button type="submit" disabled={isPending}>
        {isPending ? '確認中…' : '入力内容を確認する'}
      </button>
      {state.kind === 'ok' ? <p>{state.message}</p> : null}
    </form>
  );
}
