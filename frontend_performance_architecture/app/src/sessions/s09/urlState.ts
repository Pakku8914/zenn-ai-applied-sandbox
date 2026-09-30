import { useSyncExternalStore } from 'react';
import {
  DEFAULT_QUERY,
  decideHistoryMode,
  parseCatalogQuery,
  toSearch,
  type CatalogQuery,
  type ChangeKind,
} from './catalogQuery';

// pushState / replaceState は popstate を発火しない。自分で変えたことを知らせるための合図
const LOCATION_CHANGE = 's09:locationchange';

// 「いま入力の途中か」は画面に出さない情報なので、React の state にしない
let typing = false;

function subscribeLocation(onChange: () => void): () => void {
  const onPopState = () => {
    typing = false; // 戻る・進むで別の履歴に移ったら、入力の続きではなくなる
    onChange();
  };
  window.addEventListener('popstate', onPopState);
  window.addEventListener(LOCATION_CHANGE, onChange);
  return () => {
    window.removeEventListener('popstate', onPopState);
    window.removeEventListener(LOCATION_CHANGE, onChange);
  };
}

/**
 * URL を「ブラウザが持っている外部ストア」として読む。
 * selector はプリミティブ（文字列など）を返すこと。毎回新しいオブジェクトを返すと無限ループになる。
 */
export function useCatalogSelector<S>(selector: (query: CatalogQuery) => S): S {
  return useSyncExternalStore(
    subscribeLocation,
    () => selector(parseCatalogQuery(window.location.search)),
    () => selector(DEFAULT_QUERY),
  );
}

/** イベントハンドラの中では、描画時の値ではなくいまの URL を読む（古い値で上書きしないため） */
export function readCatalogQuery(): CatalogQuery {
  return parseCatalogQuery(window.location.search);
}

/** 状態の一部を変えて URL に書く。履歴の積み方は操作の種類で決める */
export function updateCatalog(patch: Partial<CatalogQuery>, kind: ChangeKind): void {
  const mode = decideHistoryMode(typing, kind);
  typing = kind === 'typing';

  const { pathname, search, hash } = window.location;
  const nextUrl = `${pathname}${toSearch({ ...readCatalogQuery(), ...patch })}${hash}`;
  if (nextUrl === `${pathname}${search}${hash}`) return; // 同じ URL を履歴に積まない

  if (mode === 'push') {
    window.history.pushState(null, '', nextUrl);
  } else {
    window.history.replaceState(null, '', nextUrl);
  }
  window.dispatchEvent(new Event(LOCATION_CHANGE));
}

/** 入力を確定した（Enter・フォーカスが外れた）ら、次の1文字は新しい履歴として積む */
export function endTyping(): void {
  typing = false;
}
