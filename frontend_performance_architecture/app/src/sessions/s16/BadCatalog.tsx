import { useEffect, useState, type CSSProperties } from 'react';
import type { Product } from '../../data/products';
import type { FakeApi } from '../s10/fakeApi';
import { OVERSCAN, ROW_HEIGHT, RowCells, VIEWPORT_HEIGHT, listStyle, pageStyle, rowStyle, viewportStyle } from '../s11/rows';
import { computeWindow } from '../s11/windowing';
import { CATEGORY_OPTIONS, type CategoryOption } from './a11yModel';
import { loadCatalog } from './catalogApi';

const inputStyle: CSSProperties = { display: 'block', width: '100%', padding: 8, boxSizing: 'border-box' };

const chipStyle = (checked: boolean): CSSProperties => ({
  padding: '4px 12px',
  borderRadius: 16,
  cursor: 'pointer',
  background: checked ? '#1d4ed8' : '#e5e7eb',
  color: checked ? '#fff' : '#111',
});

const overlayStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(0, 0, 0, 0.4)',
};

const boxStyle: CSSProperties = { background: '#fff', borderRadius: 8, padding: 24, minWidth: 320 };

/**
 * Bad 版：マウスでは問題なく使えるが、キーボードとスクリーンリーダーでは使えないカタログ。
 * 見た目は Good 版とほぼ同じにしてあり、違いはマークアップとフォーカスの扱いだけ。
 */
export function BadCatalog({ api, failLoad }: { api: FakeApi; failLoad: boolean }) {
  const [items, setItems] = useState<readonly Product[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<CategoryOption>('すべて');
  const [opened, setOpened] = useState<Product | null>(null);
  const [scrollTop, setScrollTop] = useState(0);

  useEffect(() => {
    loadCatalog(api, { attempt: 0, failFirstAttempt: failLoad }).then(setItems, () => setFailed(true));
  }, [api, failLoad]);

  const filtered = (items ?? []).filter((p) => p.name.includes(keyword) && (category === 'すべて' || p.category === category));
  const range = computeWindow({
    itemCount: filtered.length,
    rowHeight: ROW_HEIGHT,
    viewportHeight: VIEWPORT_HEIGHT,
    scrollTop,
    overscan: OVERSCAN,
  });
  const visible = filtered.slice(range.start, range.end);

  return (
    <main className="s16-bad" style={pageStyle}>
      <h1>商品カタログ（未対応）</h1>

      {/* label が無く placeholder だけ。入力を始めると、何の欄かが画面からも消える */}
      <input id="keyword" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="商品名で絞り込み" style={inputStyle} />

      <div style={{ display: 'flex', gap: 8, margin: '12px 0' }}>
        {CATEGORY_OPTIONS.map((c) => (
          // div にクリックだけを付けた「ボタンもどき」。Tab で止まらず、Enter でも押せず、選択中かどうかも伝わらない
          <div key={c} onClick={() => setCategory(c)} style={chipStyle(c === category)}>
            {c}
          </div>
        ))}
      </div>

      {failed ? (
        <p style={{ color: '#9ca3af' }}>エラー</p>
      ) : items === null ? (
        <div className="s16-spinner" data-spinner="true" />
      ) : (
        <>
          {/* 件数は見た目だけ。変わっても支援技術には伝わらない */}
          <div style={{ color: '#9ca3af', fontSize: 12 }}>{filtered.length} 件</div>
          <div data-viewport="true" style={viewportStyle} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}>
            <div style={{ height: range.paddingTop }} />
            <ul style={listStyle}>
              {visible.map((p) => (
                // 全行が Tab で止まる。フォーカス中の行がスクロールで DOM から消えると、フォーカスは body へ落ちる
                <li key={p.id} tabIndex={0} style={rowStyle} onClick={() => setOpened(p)}>
                  <RowCells product={p} />
                </li>
              ))}
            </ul>
            <div style={{ height: range.paddingBottom }} />
          </div>
        </>
      )}

      {opened !== null && (
        // 見た目だけのダイアログ。フォーカスは移らず、Escape でも閉じず、閉じたあとの行き先も決めていない
        <div data-bad-dialog="true" style={overlayStyle}>
          <div style={boxStyle}>
            <div style={{ fontWeight: 'bold' }}>{opened.name} の詳細</div>
            <p>
              {opened.price} 円・{opened.category}
            </p>
            <button type="button" onClick={() => setOpened(null)}>
              ×
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
