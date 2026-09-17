// ログイン・新規登録のフォームが useActionState で受け渡す状態（セッション25）。
//
// 'use server' を付けたファイルからは async 関数しか export できないため、
// 型・初期値・小さなヘルパーはこの普通のモジュールに置き、
// サーバー側（actions.ts）とクライアント側（*Form.tsx）の両方から読む。

/** フォームの状態。判別のためのタグは本書共通の kind */
export type AuthFormState = { kind: 'idle' } | { kind: 'error'; message: string };

export const INITIAL_AUTH_FORM_STATE: AuthFormState = { kind: 'idle' };

export function authFormError(message: string): AuthFormState {
  return { kind: 'error', message };
}

/** FormData から文字列を1つ取り出す。文字列でない値（ファイルなど）は空文字にする */
export function readFormString(formData: FormData, key: string): string {
  const value = formData.get(key);

  return typeof value === 'string' ? value : '';
}
