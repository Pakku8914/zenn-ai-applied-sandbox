// 「数値・状態」を「画面に出す文字列」に変える関数だけを置くモジュール。
// 画面（.tsx）の中に整形処理を書くとテストできなくなるため、ここに切り出している。

import type { CartLine } from '@/lib/cart';

/**
 * 整数の円を「1,000円」の形にする。
 * 金額は整数のまま計算し、表示の直前だけ文字列にする（セッション2で決めた方針）。
 */
export function formatYen(amount: number): string {
  const sign = amount < 0 ? '-' : '';
  const digits = String(Math.abs(amount));
  const headLength = digits.length % 3 === 0 ? 3 : digits.length % 3;
  const groups: string[] = [digits.slice(0, headLength)];

  for (let start = headLength; start < digits.length; start += 3) {
    groups.push(digits.slice(start, start + 3));
  }

  return `${sign}${groups.join(',')}円`;
}

/** これ以下になったら残数を出す（練習問題2。S16・Mid01 と同じ値） */
export const LOW_STOCK_THRESHOLD = 5;

/** 在庫数を利用者向けのラベルにする（練習問題2） */
export function stockLabel(stock: number): string {
  if (stock <= 0) {
    return '在庫切れ';
  }

  if (stock <= LOW_STOCK_THRESHOLD) {
    return `残り${stock}点`;
  }

  return '在庫あり';
}

/**
 * カート明細のリストで key に使う文字列。
 * 明細の識別子が変わっても（セッション23でデータベースの行 id になる）直す場所はここだけ。
 */
export function cartLineKey(line: CartLine): string {
  return `line-${line.product.id}`;
}
