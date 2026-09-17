import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { LoginForm } from '@/components/LoginForm';
import { resolveNextPath } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';

export const metadata: Metadata = { title: 'ログイン' };

type LoginPageProps = {
  // searchParams は Next.js 15 から Promise（セッション21）
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const raw = await searchParams;
  const rawNext = raw['next'];

  // ?next= は利用者が自由に書ける値。外部サイトの URL を弾いてから使う
  const nextPath = resolveNextPath(typeof rawNext === 'string' ? rawNext : null);
  const user = await getSessionUser();

  // すでにログインしている人にログイン画面を見せる意味はない
  if (user !== undefined) {
    redirect(nextPath);
  }

  return (
    <div>
      <h1>ログイン</h1>

      <LoginForm nextPath={nextPath} />

      <p>
        はじめての方は <Link href="/signup">新規登録</Link> へ。
      </p>
    </div>
  );
}
