import { ProductRows } from '../../lib/s12/ProductRows';
import { filterProducts } from '../../lib/s12/products';
import { SearchBox } from './SearchBox';

export const metadata = { title: 'S12 RSC 版（境界を葉に寄せた版）' };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

/**
 * サーバーコンポーネント（ディレクティブなし）。一覧はサーバーで絞り込んで HTML にする。
 * searchParams を読むので、このページはリクエストごとに描画される（動的レンダリング）。
 */
export default async function Page({ searchParams }: Props) {
  const { q } = await searchParams;
  const keyword = typeof q === 'string' ? q : '';
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（RSC 版）</h1>
      {/* クライアントに送るのは、この入力欄（葉）だけ。props は文字列 1 つ */}
      <SearchBox initialKeyword={keyword} />
      <ProductRows products={filterProducts(keyword)} />
    </main>
  );
}
