import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { Product } from '../../data/products';
import { ApiError, isAbortError, type FakeApi } from '../s10/fakeApi';
import { rollbackFavorite, withFavorite, type Favorites } from '../s10/optimistic';
import { ROW_HEIGHT, VIEWPORT_HEIGHT, pageStyle, rowStyle, viewportStyle } from '../s11/rows';
import { AccessibleList } from './AccessibleList';
import { CategoryRadios } from './CategoryRadios';
import { ProductDialog } from './ProductDialog';
import { LOADING_MESSAGE, loadErrorMessage, resultMessage, saveErrorMessage, type CategoryOption } from './a11yModel';
import { loadCatalog } from './catalogApi';
import { useDebouncedValue } from './useDebouncedValue';

type Load =
  | { status: 'loading' }
  | { status: 'error'; code: number }
  | { status: 'ready'; items: readonly Product[] };

type Props = {
  api: FakeApi;
  failLoad: boolean;
  liveDelayMs: number;
};

const inputStyle: CSSProperties = { display: 'block', width: '100%', padding: 8, boxSizing: 'border-box' };
const statusStyle: CSSProperties = { minHeight: '1.5em', margin: '4px 0', color: '#374151' };
const alertStyle: CSSProperties = { padding: 12, margin: '8px 0', borderRadius: 8, background: '#fef2f2', color: '#991b1b' };

/** 読み込み中の見た目。本物と同じ枠・同じ行の高さで作り（S11）、読み上げの対象からは外す */
function ListSkeleton() {
  return (
    <div data-skeleton="true" aria-hidden="true" style={{ ...viewportStyle, overflowY: 'hidden' }}>
      {Array.from({ length: VIEWPORT_HEIGHT / ROW_HEIGHT }, (_, i) => (
        <div key={i} style={{ ...rowStyle, padding: '0 8px' }}>
          <div className="s16-skeleton-bar" data-skeleton-bar="true" />
        </div>
      ))}
    </div>
  );
}

/** Good 版：キーボードだけで全操作でき、件数・待ち時間・失敗がスクリーンリーダーにも伝わるカタログ */
export function GoodCatalog({ api, failLoad, liveDelayMs }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<CategoryOption>('すべて');
  const [opened, setOpened] = useState<Product | null>(null);
  const [favorites, setFavorites] = useState<Favorites>(() => new Set<number>());
  const [saveError, setSaveError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const keywordRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    loadCatalog(api, { attempt, failFirstAttempt: failLoad, signal: controller.signal }).then(
      (items) => setLoad({ status: 'ready', items }),
      (error: unknown) => {
        if (!isAbortError(error)) setLoad({ status: 'error', code: error instanceof ApiError ? error.status : 0 });
      },
    );
    return () => controller.abort();
  }, [api, attempt, failLoad]);

  const all = load.status === 'ready' ? load.items : [];
  const filtered = all.filter((p) => p.name.includes(keyword) && (category === 'すべて' || p.category === category));
  const isFiltered = keyword !== '' || category !== 'すべて';
  const message =
    load.status === 'loading' ? LOADING_MESSAGE : load.status === 'error' ? '' : resultMessage(filtered.length, all.length, isFiltered);
  // 見出しの件数はすぐ変える（見た目を先に返す）。読み上げは打ち終わってから 1 回だけ
  const announced = useDebouncedValue(message, liveDelayMs);

  function retry() {
    setLoad({ status: 'loading' });
    setAttempt((a) => a + 1);
    // 押したボタンは alert ごと消える。消える前に行き先（一覧の見出し）を決めておかないと body に落ちる
    headingRef.current?.focus();
  }

  function clearFilters() {
    setKeyword('');
    setCategory('すべて');
    keywordRef.current?.focus();
  }

  function toggleFavorite(product: Product) {
    const on = !favorites.has(product.id);
    setFavorites((current) => withFavorite(current, product.id, on)); // 楽観的UI：応答を待たずに切り替える
    setSaveError(null);
    api.setFavorite(product.id, on).catch(() => {
      setFavorites((current) => rollbackFavorite(current, product.id, on));
      setSaveError(saveErrorMessage(product.name));
    });
  }

  function closeDialog() {
    setOpened(null);
    setSaveError(null);
  }

  return (
    <main className="s16-good" style={pageStyle}>
      <h1>商品カタログ（アクセシビリティ対応）</h1>

      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        ref={keywordRef}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="例: 商品1"
        autoComplete="off"
        style={inputStyle}
      />
      <CategoryRadios value={category} onChange={setCategory} />

      {/* ライブリージョンは最初から DOM に置いておき、中身だけを書き換える */}
      <p role="status" style={statusStyle}>
        {announced}
      </p>

      {load.status === 'error' && (
        <div role="alert" style={alertStyle}>
          <p style={{ margin: '0 0 8px' }}>{loadErrorMessage(load.code)}</p>
          <button type="button" onClick={retry}>
            もう一度読み込む
          </button>
        </div>
      )}

      <section aria-labelledby="list-heading" aria-busy={load.status === 'loading'}>
        <h2 id="list-heading" ref={headingRef} tabIndex={-1}>
          商品一覧{load.status === 'ready' ? `（${filtered.length} 件）` : ''}
        </h2>
        {load.status === 'loading' && <ListSkeleton />}
        {load.status === 'ready' && filtered.length > 0 && (
          // 絞り込み条件が変わったら一覧を作り直し、スクロール位置と「いまの行」を先頭に戻す
          <AccessibleList key={`${keyword}|${category}`} items={filtered} onOpen={setOpened} />
        )}
        {load.status === 'ready' && filtered.length === 0 && (
          <p>
            該当する商品はありません。{' '}
            <button type="button" onClick={clearFilters}>
              条件をクリア
            </button>
          </p>
        )}
      </section>

      <ProductDialog
        product={opened}
        favorite={opened !== null && favorites.has(opened.id)}
        error={saveError}
        onToggleFavorite={toggleFavorite}
        onClose={closeDialog}
      />
    </main>
  );
}
