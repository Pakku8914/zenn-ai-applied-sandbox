import { useEffect, useSyncExternalStore } from 'react';
import type { QueryCache, QueryState } from './cache';

export function useQuery<T>(cache: QueryCache<T>, key: string): QueryState<T> {
  const state = useSyncExternalStore(cache.subscribe, () => cache.getState(key), () => cache.getState(key));
  useEffect(() => {
    cache.ensure(key);
  }, [cache, key]);
  return state;
}
