import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { SignupForm } from '@/components/SignupForm';
import { PASSWORD_MIN_LENGTH } from '@/lib/auth';
import { getSessionUser } from '@/lib/session';

export const metadata: Metadata = { title: '新規登録' };

export default async function SignupPage() {
  const user = await getSessionUser();

  if (user !== undefined) {
    redirect('/');
  }

  return (
    <div>
      <h1>新規登録</h1>

      {/* サーバー側の定数を props で渡す。フォームは lib/auth.ts を直接読まない */}
      <SignupForm minLength={PASSWORD_MIN_LENGTH} />

      <p>
        登録済みの方は <Link href="/login">ログイン</Link> へ。
      </p>
    </div>
  );
}
