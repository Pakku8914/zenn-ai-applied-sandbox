import { useSyncExternalStore } from 'react';
import type { Store } from './createStore';

/**
 * ストアの一部だけを選んで読む。選んだ値が変わったときだけ再レンダリングされる。
 * selector は数値・文字列などのプリミティブか、ストア内の既存の参照を返すこと。
 * `s.ids.filter(...)` のように毎回新しい配列を返すと「値が変わった」とみなされ続けて無限ループになる。
 */
export function useStore<T, S>(store: Store<T>, selector: (state: T) => S): S {
  const read = () => selector(store.getState());
  return useSyncExternalStore(store.subscribe, read, read);
}
