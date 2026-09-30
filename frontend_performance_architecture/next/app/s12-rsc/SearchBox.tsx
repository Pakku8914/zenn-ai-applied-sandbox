'use client';

import { useEffect, useState, useTransition } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { markHydrated } from '../../lib/s12/browser';

/**
 * 入力欄だけのクライアントコンポーネント。入力は URL（?q=）に書き、一覧はサーバーが描き直す。
 * 入力欄の更新は即座に、一覧の差し替えは transition で後から行う。
 */
export function SearchBox({ initialKeyword }: { initialKeyword: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const [value, setValue] = useState(initialKeyword);
  const [isPending, startTransition] = useTransition();

  useEffect(markHydrated, []);

  return (
    <>
      <label htmlFor="keyword">商品名で絞り込み</label>
      <input
        id="keyword"
        value={value}
        onChange={(e) => {
          const next = e.target.value;
          setValue(next);
          startTransition(() => {
            const href = next === '' ? pathname : `${pathname}?q=${encodeURIComponent(next)}`;
            router.replace(href, { scroll: false });
          });
        }}
        placeholder="例: 商品1"
        style={{ display: 'block', width: '100%', padding: 8, marginBottom: 16 }}
      />
      {/* 高さを先に確保しておき、文言の出し入れでレイアウトをずらさない（CLS 対策） */}
      <p aria-live="polite" style={{ minHeight: '1.5em', margin: 0, color: '#666' }}>
        {isPending ? 'サーバーで絞り込み中…' : ''}
      </p>
    </>
  );
}
