import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { AuthStatus } from '@/components/AuthStatus';

// すべてのページに共通するタイトルと説明。
// template を書いておくと、各ページが title を返したときに「%s | ミニ雑貨ショップ」になる。
export const metadata: Metadata = {
  title: {
    default: 'ミニ雑貨ショップ',
    template: '%s | ミニ雑貨ショップ',
  },
  description: '暮らしを少し楽しくする雑貨のオンラインショップです。',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header>
          <nav>
            <Link href="/">ホーム</Link> <Link href="/products">商品一覧</Link>{' '}
            <Link href="/cart">カート</Link>
          </nav>
          {/* ログイン状態の表示（セッション25）。セッションを読むため、
              この行が入った時点でサイト全体が「毎回サーバーで作る」ページになる */}
          <AuthStatus />
        </header>
        <main>{children}</main>
        <footer>
          <small>ミニ雑貨ショップ（学習用のサンプルです）</small>
        </footer>
      </body>
    </html>
  );
}
