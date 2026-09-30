'use client';

import { useEffect, useState } from 'react';
import { markHydrated } from '../../lib/s12/browser';

export function FavoriteButton({ productId }: { productId: number }) {
  const [pressed, setPressed] = useState(false);

  useEffect(markHydrated, []);

  return (
    <button
      type="button"
      data-favorite={productId}
      aria-pressed={pressed}
      onClick={() => setPressed((v) => !v)}
    >
      {pressed ? 'お気に入り済み' : 'お気に入りに追加'}
    </button>
  );
}
