import { useEffect, useState, type CSSProperties } from 'react';
import { HeavyChart } from '../../../components/HeavyChart';
import { renderPrintCard } from '../../s05/print/renderPrintCard';
import { PRODUCTS_20K } from '../../s08/products20k';

/**
 * 最終プロジェクトの出題版。見た目は出発点と同じ商品カタログで、件数だけが 20,000 件になっている。
 * 読み込み・描画・入力応答・状態の置き場所・アクセシビリティ・構成の問題を、1 ファイルにまとめて抱えている。
 * どこが何の問題かは、コードを読む前に計測で当たりを付けること。このファイルは書き換えない（前後比較の「前」）。
 */
const bannerStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: 280,
  margin: '16px 0',
  padding: 24,
  borderRadius: 12,
  background: '#fef3c7',
  fontSize: 16,
};

/** 少し遅れて文言が届くキャンペーンバナー（マーケティング部門の要件なので外せない） */
function LateBanner() {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    const id = setTimeout(() => setText('今週末は送料無料。3,000 円以上のご注文が対象です。'), 300);
    return () => clearTimeout(id);
  }, []);
  if (text === null) return null;
  return (
    <aside style={bannerStyle} data-campaign="loaded">
      {text}
    </aside>
  );
}

export function StartCatalog() {
  const [keyword, setKeyword] = useState('');
  const [showChart, setShowChart] = useState(false);
  const [printHtml, setPrintHtml] = useState('');
  const filtered = PRODUCTS_20K.filter((p) => p.name.includes(keyword));

  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>商品カタログ（計測用）</h1>

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
      {showChart ? <HeavyChart /> : null}

      <LateBanner />

      <section>
        <h2>商品一覧（{filtered.length} 件）</h2>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {filtered.map((p) => (
            <li key={p.id} style={{ borderBottom: '1px solid #ddd', padding: '8px 0', display: 'flex', gap: 12 }}>
              {/* 商品名を押すと、その商品の印刷用 HTML を作る */}
              <button
                type="button"
                onClick={() => setPrintHtml(renderPrintCard(p))}
                style={{ width: 120, textAlign: 'left', background: 'none', border: 'none', padding: 0, font: 'inherit' }}
              >
                {p.name}
              </button>
              <span style={{ width: 80, textAlign: 'right' }}>{p.price} 円</span>
              <span style={{ color: '#666' }}>{p.category}</span>
            </li>
          ))}
        </ul>
      </section>

      <pre id="print-output" style={{ whiteSpace: 'pre-wrap' }}>
        {printHtml}
      </pre>
    </main>
  );
}
