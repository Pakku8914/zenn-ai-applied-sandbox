'use client';

// クリックに反応して自分の中に状態を持つ部品。だからクライアントコンポーネントにする。
// 境界はこの小さな部品に置く。一覧ページ自体はサーバーコンポーネントのまま。

import { useState } from 'react';

type AddToCartButtonProps = {
  /** 表示に使う商品名。関数やクラスのインスタンスは境界を越えられないので、値だけを受け取る */
  productName: string;
  soldOut: boolean;
};

export function AddToCartButton({ productName, soldOut }: AddToCartButtonProps) {
  const [selectedCount, setSelectedCount] = useState(0);

  if (soldOut) {
    return <span>入荷をお待ちください</span>;
  }

  return (
    <span>
      {/* 更新関数を渡す形。直前の値から次の値を作るので、連続して押しても数え落とさない */}
      <button type="button" onClick={() => setSelectedCount((previous) => previous + 1)}>
        カートに追加
      </button>
      {selectedCount === 0 ? null : <span>{`（${productName} を ${selectedCount}点）`}</span>}
    </span>
  );
}
