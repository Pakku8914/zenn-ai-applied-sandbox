import type { ReactNode } from 'react';

type Props = {
  onClick: () => void;
  children: ReactNode;
};

/** 見た目だけを決める部品。商品もカートも知らない */
export function Button({ onClick, children }: Props) {
  return (
    <button type="button" onClick={onClick} style={{ padding: '2px 8px' }}>
      {children}
    </button>
  );
}
