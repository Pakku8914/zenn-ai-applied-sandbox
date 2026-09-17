import type { ReactNode } from 'react';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { AccessDenied } from '@/components/AccessDenied';
import { judgeAdminAccess } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';

// 管理画面の共通の枠。ここが管理画面全体の2枚目の門番になる
// （1枚目は middleware.ts、3枚目は各ページとデータを取る関数）。
export default async function AdminLayout({ children }: { children: ReactNode }) {
  const user = await getSessionUser();
  const failure = judgeAdminAccess(user);

  if (failure !== null && failure.kind === 'unauthenticated') {
    redirect(`/login?next=${encodeURIComponent('/admin')}`);
  }

  if (failure !== null) {
    // ログインはしているが管理者ではない＝403。ログイン画面へ送っても解決しない
    return <AccessDenied status={403} description="管理者だけが開けるページです。" />;
  }

  return (
    <section>
      <p>
        <Link href="/admin">管理トップ</Link> <Link href="/admin/products">商品マスタ</Link>{' '}
        <Link href="/admin/orders">注文一覧</Link>
      </p>

      {children}
    </section>
  );
}
