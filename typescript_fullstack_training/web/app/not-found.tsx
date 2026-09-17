import Link from 'next/link';

// 存在しない URL に来たとき、および notFound() が呼ばれたときに表示される画面。
export default function NotFound() {
  return (
    <div>
      <h1>ページが見つかりません</h1>
      <p>URL が変わったか、商品が取り扱い終了になった可能性があります。</p>
      <p>
        <Link href="/products">商品一覧へ</Link>
      </p>
    </div>
  );
}
