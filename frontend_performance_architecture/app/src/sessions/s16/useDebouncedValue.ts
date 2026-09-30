import { useEffect, useState } from 'react';

/** value が delayMs のあいだ変わらなかったら、その値を返す。delayMs が 0 以下なら即座に返す（比較用） */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    if (delayMs <= 0) return;
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return delayMs <= 0 ? value : debounced;
}
