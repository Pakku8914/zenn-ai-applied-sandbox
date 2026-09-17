'use client';

// カートの状態を持つ部品。状態を持つ＝クライアントコンポーネントにする理由。
// 状態の更新はすべて lib/cart.ts の純粋関数に任せ、この部品は「呼ぶだけ」にしている。

import { useEffect, useState } from 'react';
import type { Product } from '@/lib/products';
import {
  CART_STORAGE_KEY,
  addLine,
  calcTotalQuantity,
  changeQuantity,
  isAtMaxQuantity,
  parseStoredCart,
  removeLine,
  toStoredCart,
  type CartLine,
} from '@/lib/cart';
import { cartLineKey, formatYen } from '@/lib/format';
import { buildPaymentSummary, calcLineTotal } from '@/lib/pricing';
import { CartSummary } from '@/components/CartSummary';
import { QuantitySelect } from '@/components/QuantitySelect';

type CartPanelProps = {
  /** サーバーから渡ってくるのは JSON にできる値だけ。商品の配列はそのまま渡せる */
  products: readonly Product[];
};

export function CartPanel({ products }: CartPanelProps) {
  const [lines, setLines] = useState<CartLine[]>([]);
  const [restored, setRestored] = useState(false);

  // ブラウザに保存された内容を読み戻す（練習問題7）。
  // useState の初期値ではなく useEffect で読むのは、サーバー側に localStorage が無いため。
  useEffect(() => {
    setLines(parseStoredCart(window.localStorage.getItem(CART_STORAGE_KEY), products));
    setRestored(true);
  }, [products]);

  // 明細が変わるたびに保存する。読み戻す前に空の配列で上書きしないよう restored を見る
  useEffect(() => {
    if (!restored) {
      return;
    }

    window.localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(toStoredCart(lines)));
  }, [lines, restored]);

  // 明細から決まる値は state にしない。描画のたびに計算すれば必ず最新になる
  const totalQuantity = calcTotalQuantity(lines);
  const summary = buildPaymentSummary(lines);

  return (
    <div>
      <h2>商品を選ぶ</h2>
      <ul>
        {products.map((product) => (
          <li key={product.id}>
            {`${product.name}（${formatYen(product.price)}） `}
            {product.stock === 0 ? (
              <span>在庫切れ</span>
            ) : (
              <button type="button" onClick={() => setLines((previous) => addLine(previous, product))}>
                カートに入れる
              </button>
            )}
          </li>
        ))}
      </ul>

      <h2>{`カートの中身（${totalQuantity}点）`}</h2>
      {lines.length === 0 ? (
        <p>カートは空です。商品を選んでください。</p>
      ) : (
        <ul>
          {lines.map((line) => (
            <li key={cartLineKey(line)}>
              {`${line.product.name} `}
              <QuantitySelect
                quantity={line.quantity}
                stock={line.product.stock}
                onChangeQuantity={(quantity) =>
                  setLines((previous) => changeQuantity(previous, line.product.id, quantity))
                }
              />
              {` 小計 ${formatYen(calcLineTotal(line.product.price, line.quantity))} `}
              <button
                type="button"
                onClick={() => setLines((previous) => removeLine(previous, line.product.id))}
              >
                削除
              </button>
              {isAtMaxQuantity(line) ? <span>これ以上増やせません</span> : null}
            </li>
          ))}
        </ul>
      )}

      {/* 空のカートで「送料500円・支払総額500円」と出すのは正しくない。
          計算の手順は変えず、表示する条件だけをここで決める */}
      {lines.length === 0 ? null : <CartSummary summary={summary} />}
    </div>
  );
}
