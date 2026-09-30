import type { ReactNode } from 'react';

type Props = {
  title: string;
  /** 見出しの下に置く操作（検索・並び替えなど）。中身は使う側が決める */
  toolbar?: ReactNode;
  children: ReactNode;
};

/** 再利用できる部品。商品もカートも知らず、枠と置き場所（スロット）だけを持つ */
export function PageLayout({ title, toolbar, children }: Props) {
  return (
    <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <h1>{title}</h1>
      {toolbar ? <div style={{ marginBottom: 16 }}>{toolbar}</div> : null}
      {children}
    </main>
  );
}
