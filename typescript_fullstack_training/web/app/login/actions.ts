'use server';

// ログインの処理（セッション25）。
// 「誰か」を確かめ、確かめられたらセッションを作る。ここから先はサーバーだけの世界。

import { redirect } from 'next/navigation';
import { DUMMY_PASSWORD_HASH, verifyPassword } from '@/lib/auth';
import { resolveNextPath } from '@/lib/authz';
import { prisma } from '@/lib/db';
import { createSession } from '@/lib/session';
import { authFormError, readFormString, type AuthFormState } from '@/components/auth-form-state';

/** 失敗の理由を細かく分けない（どちらが違うかを教えると宛先の存在が漏れる） */
const LOGIN_FAILED_MESSAGE = 'メールアドレスまたはパスワードが正しくありません';

export async function loginAction(
  _previousState: AuthFormState,
  formData: FormData
): Promise<AuthFormState> {
  const email = readFormString(formData, 'email').trim().toLowerCase();
  const password = readFormString(formData, 'password');
  const nextPath = resolveNextPath(readFormString(formData, 'next'));

  if (email === '' || password === '') {
    return authFormError('メールアドレスとパスワードを入力してください');
  }

  const user = await prisma.user.findUnique({
    where: { email },
    select: { id: true, passwordHash: true },
  });

  // 利用者が見つからなくても、見つかったときと同じだけ計算する。
  // すぐに失敗を返すと、応答の速さから「その宛先は登録されている」と分かってしまう
  const matched = await verifyPassword(password, user?.passwordHash ?? DUMMY_PASSWORD_HASH);

  if (user === null || !matched) {
    // ログに残してよいのは「失敗した事実」だけ。パスワードは絶対に出さない（セッション18）
    console.warn(`ログインに失敗しました: ${email}`);

    return authFormError(LOGIN_FAILED_MESSAGE);
  }

  await createSession(user.id);

  // redirect は例外を投げて画面を切り替える。try の中で呼ぶと catch に拾われるので外で呼ぶ
  redirect(nextPath);
}
