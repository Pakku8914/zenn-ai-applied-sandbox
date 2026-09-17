'use client';

// 新規登録フォーム（セッション25）。
// role を選ばせる入力は置かない。役割はサーバー側で 'user' に固定する。
//
// このファイルからは lib/auth.ts を import しない。あちらは node:crypto を使うため、
// クライアントコンポーネントが読み込むとブラウザ向けのバンドルに混ざってビルドが失敗する。
// 画面に出したい値（最低文字数）は props でサーバー側から受け取る。

import { useActionState } from 'react';
import { signupAction } from '@/app/signup/actions';
import { INITIAL_AUTH_FORM_STATE } from '@/components/auth-form-state';

type SignupFormProps = {
  /** パスワードの最低文字数。lib/auth.ts の PASSWORD_MIN_LENGTH をページから渡す */
  minLength: number;
};

export function SignupForm({ minLength }: SignupFormProps) {
  const [state, formAction, pending] = useActionState(signupAction, INITIAL_AUTH_FORM_STATE);

  return (
    <form action={formAction}>
      <p>
        <label htmlFor="signup-name">お名前</label>
        <br />
        <input id="signup-name" name="name" type="text" autoComplete="name" required />
      </p>

      <p>
        <label htmlFor="signup-email">メールアドレス</label>
        <br />
        <input id="signup-email" name="email" type="email" autoComplete="email" required />
      </p>

      <p>
        <label htmlFor="signup-password">
          {`パスワード（${minLength}文字以上・英字と数字を含む）`}
        </label>
        <br />
        <input
          id="signup-password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={minLength}
          required
        />
      </p>

      {/* ブラウザ側の required や minLength は入力のしやすさのため。
          通してはいけない値を止めるのはサーバー側の検証（前章のとおり） */}
      {state.kind === 'error' ? <p role="alert">{state.message}</p> : null}

      <button type="submit" disabled={pending}>
        {pending ? '登録中…' : '登録する'}
      </button>
    </form>
  );
}
