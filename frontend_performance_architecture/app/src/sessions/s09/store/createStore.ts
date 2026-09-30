export type Store<T> = {
  getState: () => T;
  setState: (update: (prev: T) => T) => void;
  subscribe: (listener: () => void) => () => void;
};

/**
 * React の外に状態を置く、最小の外部ストア。
 * useSyncExternalStore に渡す subscribe と getState の2つさえあればよい。
 */
export function createStore<T>(initial: T): Store<T> {
  let state = initial;
  const listeners = new Set<() => void>();

  return {
    getState: () => state,
    setState: (update) => {
      const next = update(state);
      if (Object.is(next, state)) return; // 変わっていなければ誰にも知らせない
      state = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
