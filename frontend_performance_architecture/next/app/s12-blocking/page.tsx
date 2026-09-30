import { RankingList } from '../../lib/s12/RankingList';
import { loadRanking } from '../../lib/s12/ranking';

export const metadata = { title: 'S12 遅いデータを待たせる版' };
export const dynamic = 'force-dynamic';

/** Bad：ページの先頭で遅いデータを await するので、見出しまで含めて何も送れない */
export default async function Page() {
  const items = await loadRanking(); // 1,500ms かかる
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（待たせる版）</h1>
      <p>人気ランキングは集計に時間がかかるため、準備ができしだい表示します。</p>
      <RankingList items={items} />
    </main>
  );
}
