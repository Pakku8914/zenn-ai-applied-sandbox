import { Suspense } from 'react';
import { RankingList } from '../../lib/s12/RankingList';
import { loadRanking } from '../../lib/s12/ranking';

export const metadata = { title: 'S12 ストリーミング版' };
// 静的に生成されるとビルド時に待ち終わった HTML が保存され、ストリーミングが起きない。
// リクエストごとに描画させるため動的レンダリングを指定する。
export const dynamic = 'force-dynamic';

async function SlowRanking() {
  const items = await loadRanking(); // 1,500ms かかる
  return <RankingList items={items} />;
}

export default function Page() {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（ストリーミング版）</h1>
      <p>人気ランキングは集計に時間がかかるため、準備ができしだい表示します。</p>
      {/* 遅い部分だけを Suspense で囲む。外側（見出しと説明）は待たずに送られる */}
      <Suspense
        fallback={
          <p id="ranking-fallback" style={{ minHeight: 200 }}>
            人気ランキングを集計中です…
          </p>
        }
      >
        <SlowRanking />
      </Suspense>
    </main>
  );
}
