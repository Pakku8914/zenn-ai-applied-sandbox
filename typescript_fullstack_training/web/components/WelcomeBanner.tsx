// 練習問題1の解答。JSX の書き方を直したあとの形。
// サーバーコンポーネントなので、イベントハンドラは置かない（置けない）。

import Link from 'next/link';

type WelcomeBannerProps = {
  title: string;
  message: string;
};

export function WelcomeBanner({ title, message }: WelcomeBannerProps) {
  return (
    <>
      <div className="banner">
        <h2>{title}</h2>
        {/* 案内文。空のときは代わりの文を出す */}
        <p>{message === '' ? '準備中です' : message}</p>
        <br />
        <Link href="/products">商品一覧へ</Link>
      </div>
      <p>ご利用ありがとうございます</p>
    </>
  );
}
