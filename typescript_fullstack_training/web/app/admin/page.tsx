import type { Metadata } from 'next';
import Link from 'next/link';
import { AccessDenied } from '@/components/AccessDenied';
import { judgeAdminAccess, statusForFailure } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: '管理トップ' };

export default async function AdminHomePage() {
  const user = await getSessionUser();
  const failure = judgeAdminAccess(user);

  // レイアウトでも確かめているが、ページでも確かめる。
  // レイアウトは子ルート間の移動で再実行されないことがあるため、ここを省かない
  if (failure !== null) {
    return (
      <AccessDenied
        status={statusForFailure(failure)}
        description="管理者だけが開けるページです。"
      />
    );
  }

  return (
    <div>
      <h1>管理トップ</h1>

      <p>管理者としてログインしています。</p>

      <ul>
        <li>
          <Link href="/admin/products">商品マスタを見る（登録・編集・削除）</Link>
        </li>
        <li>
          <Link href="/admin/orders">注文一覧を見る</Link>
        </li>
      </ul>
    </div>
  );
}
