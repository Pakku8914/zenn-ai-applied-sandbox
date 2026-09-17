'use client';

// ログインフォーム（セッション25）。
// この部品は入力とエラー表示だけを受け持ち、照合はサーバー側の loginAction が行う。

import { useActionState } from 'react';
import { loginAction } from '@/app/login/actions';
import { INITIAL_AUTH_FORM_STATE } from '@/components/auth-form-state';

type LoginFormProps = {
  /** ログイン後に戻る先。検証済みのパスだけが渡ってくる */
  nextPath: string;
};

export function LoginForm({ nextPath }: LoginFormProps) {
  const [state, formAction, pending] = useActionState(loginAction, INITIAL_AUTH_FORM_STATE);

  return (
    <form action={formAction}>
      {/* 戻る先はフォームに隠して持たせる。値はサーバー側でもう一度検証する */}
      <input type="hidden" name="next" value={nextPath} />

      <p>
        <label htmlFor="email">メールアドレス</label>
        <br />
        <input id="email" name="email" type="email" autoComplete="email" required />
      </p>

      <p>
        <label htmlFor="password">パスワード</label>
        <br />
        {/* type="password" は画面の表示を隠すだけ。通信を守るのは HTTPS */}
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
      </p>

      {state.kind === 'error' ? <p role="alert">{state.message}</p> : null}

      <button type="submit" disabled={pending}>
        {pending ? '確認中…' : 'ログイン'}
      </button>
    </form>
  );
}
