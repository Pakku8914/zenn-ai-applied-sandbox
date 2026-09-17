import Link from 'next/link';
import { CATEGORIES } from '@/lib/products';
import { WelcomeBanner } from '@/components/WelcomeBanner';

export default function HomePage() {
  return (
    <div>
      <h1>ミニ雑貨ショップ</h1>
      <p>暮らしを少し楽しくする雑貨をそろえています。</p>

      <WelcomeBanner title="ようこそ" message="送料は税込3,000円以上のお買い上げで無料です。" />

      <h2>カテゴリから探す</h2>
      <ul>
        {CATEGORIES.map((category) => (
          <li key={category.slug}>
            <Link href={`/products?category=${category.slug}`}>{category.name}</Link>
          </li>
        ))}
      </ul>

      <p>
        <Link href="/products">すべての商品を見る</Link>
      </p>
    </div>
  );
}
