// 見出しと中身の「枠」だけを担当する部品。中身は children として受け取る。
// サーバーコンポーネント（'use client' を書いていない）。

import type { ReactNode } from 'react';

type SectionCardProps = {
  title: string;
  /** タグで囲んだ中身がそのまま入ってくる。型は react が用意している ReactNode */
  children: ReactNode;
};

export function SectionCard({ title, children }: SectionCardProps) {
  return (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
