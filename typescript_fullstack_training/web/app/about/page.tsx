// 練習問題1の解答。/about で表示されるショップ紹介ページ。
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'ショップについて',
  description: 'ミニ雑貨ショップの紹介ページです。',
};

export default function AboutPage() {
  return (
    <div>
      <h1>ショップについて</h1>
      <p>
        ミニ雑貨ショップは、暮らしを少し楽しくする日用品を少量ずつ仕入れて紹介する小さなお店です。
      </p>
      <p>石けんやふきんなど、毎日使って減っていくものを中心にそろえています。</p>
      <p>
        <Link href="/products">商品一覧を見る</Link>
      </p>
    </div>
  );
}
