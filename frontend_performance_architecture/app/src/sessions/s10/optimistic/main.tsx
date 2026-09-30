import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { products } from '../../../data/products';
import { reportWebVitals } from '../../../vitals';
import { exposeCalls } from '../browser';
import { createFakeApi } from '../fakeApi';
import { rollbackFavorite, withFavorite, type Favorites } from '../optimistic';
import { Shell } from '../parts';

// 商品3 の保存だけが必ず失敗する擬似 API（ロールバックを再現するため）
const api = createFakeApi({ failOn: { favoriteIds: [3] } });
exposeCalls(api.calls);

const items = products.slice(0, 10);

function FavoriteList() {
  const [favorites, setFavorites] = useState<Favorites>(new Set());
  const [notice, setNotice] = useState('');

  const toggle = (id: number) => {
    const attempted = !favorites.has(id);
    // 楽観的更新：応答を待たずに画面を先に変える
    setFavorites((current) => withFavorite(current, id, attempted));
    setNotice('');
    api.setFavorite(id, attempted).catch(() => {
      // 失敗したら、この操作だけを取り消し、取り消したことを利用者に伝える
      setFavorites((current) => rollbackFavorite(current, id, attempted));
      setNotice(`商品${id} のお気に入りを保存できませんでした。元に戻しました。`);
    });
  };

  return (
    <>
      <p id="notice" role="status">
        {notice}
      </p>
      <ul>
        {items.map((p) => {
          const on = favorites.has(p.id);
          return (
            <li key={p.id}>
              {p.name}{' '}
              <button type="button" data-id={p.id} aria-pressed={on} onClick={() => toggle(p.id)}>
                {on ? '★ お気に入り済み' : '☆ お気に入りに追加'}
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root が見つかりません');
}

createRoot(rootElement).render(
  <StrictMode>
    <Shell title="お気に入り（楽観的更新とロールバック）">
      <FavoriteList />
    </Shell>
  </StrictMode>,
);
reportWebVitals();
