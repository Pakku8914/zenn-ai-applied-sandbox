import { Suspense, useEffect, useState, type ReactNode } from 'react';
import { ProductList } from '../../components/ProductList';
import { CampaignBanner } from './CampaignBanner';
import { sendSearchLog } from './tags';

/** 最後の入力からこの時間だけ入力が止まったら、検索ログを 1 回だけ送る */
export const SEARCH_LOG_DEBOUNCE_MS = 500;

type Props = {
  /** グラフの描き方。通常版は PriceChart をそのまま、比較用の版は React.lazy で包んだものを渡す */
  renderChart: () => ReactNode;
};

/**
 * 中間プロジェクトの模範解答版。出題版（SlowCatalog）からのこのファイルでの変更は 2 か所だけ
 * （計測タグの実行時期は pages/mid01-fixed/index.html と fixed/main.tsx で変えている）。
 *   1. バナーは reserved（高さを先に確保する）
 *   2. 検索ログは入力ハンドラーから外し、入力が止まってから 1 回だけ送る（デバウンス）
 * 一覧（ProductList）はメモ化していない。計測した結果、直す必要がないと判断したため。
 */
export function FixedCatalog({ renderChart }: Props) {
  const [keyword, setKeyword] = useState('');
  const [showChart, setShowChart] = useState(false);

  useEffect(() => {
    if (keyword === '') return undefined;
    const id = setTimeout(() => sendSearchLog(keyword), SEARCH_LOG_DEBOUNCE_MS);
    // 次の文字が来たら前の予約を取り消す。これで送信は「入力が止まった後の 1 回」になる
    return () => clearTimeout(id);
  }, [keyword]);

  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />

      <button type="button" onClick={() => setShowChart((v) => !v)}>
        {showChart ? 'グラフを隠す' : 'グラフを表示'}
      </button>

      {showChart ? <Suspense fallback={<p>グラフを読み込み中…</p>}>{renderChart()}</Suspense> : null}

      <CampaignBanner mode="reserved" />

      <ProductList keyword={keyword} />
    </>
  );
}
