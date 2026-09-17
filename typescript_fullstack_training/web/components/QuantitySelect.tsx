// 数量を選ぶ部品（練習問題4）。
// 'use client' を書いていないが、クライアントコンポーネントから import されるので
// ブラウザ側で動く。関数を props で受け取れるのは「クライアント同士」だからである。

import { buildQuantityOptions, parseQuantity } from '@/lib/cart';

type QuantitySelectProps = {
  quantity: number;
  stock: number;
  onChangeQuantity: (quantity: number) => void;
};

export function QuantitySelect({ quantity, stock, onChangeQuantity }: QuantitySelectProps) {
  const options = buildQuantityOptions(stock);

  return (
    <select
      value={quantity}
      aria-label="数量"
      onChange={(event) => {
        const next = parseQuantity(event.target.value);

        // 解釈できない値は無視する。画面の状態を壊さないための境界の検証
        if (next !== null) {
          onChangeQuantity(next);
        }
      }}
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {`${option}点`}
        </option>
      ))}
    </select>
  );
}
