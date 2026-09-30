import { useState } from 'react';
import { ProductList } from '../../components/ProductList';
import { CampaignBanner } from './CampaignBanner';
import { PriceChart } from './PriceChart';
import { sendSearchLog } from './tags';

/**
 * 中間プロジェクトの出題版。見た目は普通の商品カタログだが、読み込み・描画・入力応答の
 * 問題を 1 つずつ仕込んである。どこが何の問題かは、コードを読む前に計測で当たりを付けること。
 * 一覧は出発点の ProductList（2,000 件・メモ化なし）をそのまま使う。
 */
export function SlowCatalog() {
  const [keyword, setKeyword] = useState('');
  const [showChart, setShowChart] = useState(false);

  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => {
          const next = e.target.value;
          setKeyword(next);
          // 検索ログを送る（マーケティング部門の要件）
          sendSearchLog(next);
        }}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />

      <button type="button" onClick={() => setShowChart((v) => !v)}>
        {showChart ? 'グラフを隠す' : 'グラフを表示'}
      </button>

      {showChart ? <PriceChart /> : null}

      <CampaignBanner mode="late" />

      <ProductList keyword={keyword} />
    </>
  );
}
