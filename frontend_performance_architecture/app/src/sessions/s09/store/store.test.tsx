import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { selectBookCount, selectCount } from './cartStore';
import { createStore } from './createStore';
import { useStore } from './useStore';

describe('createStore', () => {
  it('値が変わったら購読者に知らせる', () => {
    const store = createStore({ count: 0 });
    const listener = vi.fn();
    store.subscribe(listener);
    store.setState((s) => ({ count: s.count + 1 }));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getState().count).toBe(1);
  });

  it('同じ参照を返したら知らせない', () => {
    const store = createStore({ count: 0 });
    const listener = vi.fn();
    store.subscribe(listener);
    store.setState((s) => s);
    expect(listener).not.toHaveBeenCalled();
  });

  it('購読を解除したら知らせない', () => {
    const store = createStore({ count: 0 });
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    unsubscribe();
    store.setState((s) => ({ count: s.count + 1 }));
    expect(listener).not.toHaveBeenCalled();
  });
});

describe('cartStore のセレクタ', () => {
  it('点数と、うち書籍の数（商品1・商品5 が書籍）', () => {
    const state = { ids: [1, 2, 5] };
    expect(selectCount(state)).toBe(3);
    expect(selectBookCount(state)).toBe(2);
  });
});

describe('useStore', () => {
  it('セレクタで選んだ値を描画に使う', () => {
    const store = createStore({ ids: [1, 2, 3] as readonly number[] });
    function Count() {
      const n = useStore(store, (s) => s.ids.length);
      return <p>{n} 点</p>;
    }
    expect(renderToString(<Count />)).toMatch(/<p>3(<!-- -->)? 点<\/p>/);
  });
});
