// ヘッダに出すログイン状態（セッション25）。
//
// サーバーコンポーネントなので、セッションをそのまま読める。
// ログアウトはリンクではなくフォームの送信（POST）にする。

import Link from 'next/link';
import { logoutAction } from '@/app/logout/actions';
import { canAccessAdmin } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';

export async function AuthStatus() {
  const user = await getSessionUser();

  if (user === undefined) {
    return (
      <div>
        <Link href="/login">ログイン</Link> <Link href="/signup">新規登録</Link>
      </div>
    );
  }

  return (
    <div>
      {`${user.name} さん `}
      <Link href="/orders">注文履歴</Link>
      {/* 管理画面へのリンクは管理者にだけ見せる。ただし「隠す」は認可ではない。
          URL を直接開かれても通らないよう、サーバー側で必ず確かめている */}
      {canAccessAdmin(user) ? (
        <>
          {' '}
          <Link href="/admin">管理</Link>
        </>
      ) : null}{' '}
      <form action={logoutAction}>
        <button type="submit">ログアウト</button>
      </form>
    </div>
  );
}
