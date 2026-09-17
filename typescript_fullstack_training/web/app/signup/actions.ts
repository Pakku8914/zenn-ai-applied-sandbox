'use server';

// 新規登録の処理（セッション25）。
// パスワードは受け取ったらすぐハッシュ化し、生のままデータベースへは渡さない。

import { redirect } from 'next/navigation';
import { checkPasswordPolicy, describePasswordPolicyFailure, hashPassword } from '@/lib/auth';
import { prisma } from '@/lib/db';
import { createSession } from '@/lib/session';
import { authFormError, readFormString, type AuthFormState } from '@/components/auth-form-state';

/** Prisma の一意制約違反（P2002）かどうか。unknown を絞り込んで確かめる（セッション16） */
function isUniqueViolation(error: unknown): boolean {
  if (typeof error !== 'object' || error === null || !('code' in error)) {
    return false;
  }

  const { code } = error;

  return typeof code === 'string' && code === 'P2002';
}

export async function signupAction(
  _previousState: AuthFormState,
  formData: FormData
): Promise<AuthFormState> {
  const name = readFormString(formData, 'name').trim();
  const email = readFormString(formData, 'email').trim().toLowerCase();
  const password = readFormString(formData, 'password');

  if (name === '' || email === '') {
    return authFormError('お名前とメールアドレスを入力してください');
  }

  if (!/^[^@\s]+@[^@\s]+$/.test(email)) {
    return authFormError('メールアドレスの形式が正しくありません');
  }

  const policyFailure = checkPasswordPolicy(password);

  if (policyFailure !== null) {
    return authFormError(describePasswordPolicyFailure(policyFailure));
  }

  const passwordHash = await hashPassword(password);

  try {
    const created = await prisma.user.create({
      // role はフォームの値を使わず 'user' で固定する。
      // 送られてきた値をそのまま入れると、誰でも管理者として登録できてしまう
      data: { email, name, passwordHash, role: 'user' },
      select: { id: true },
    });

    await createSession(created.id);
  } catch (error: unknown) {
    if (isUniqueViolation(error)) {
      return authFormError('このメールアドレスは登録済みです');
    }

    throw error;
  }

  redirect('/');
}
