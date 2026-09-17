'use server';

// ログアウトの処理（セッション25）。
// リンク（GET）ではなくフォームの送信（POST）で行う。GET にすると、
// 別サイトに置かれた画像タグを表示しただけでログアウトさせられてしまう。

import { redirect } from 'next/navigation';
import { destroySession } from '@/lib/session';

export async function logoutAction(): Promise<void> {
  await destroySession();

  redirect('/');
}
