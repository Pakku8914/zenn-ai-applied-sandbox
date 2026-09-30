import type { Product } from '../../../data/products';

// HTML として意味を持つ5文字。react-dom/server と同じ置き換え方にそろえる
const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#x27;',
};

/** 文字列を HTML の本文・属性値に埋め込んでも安全な形にする */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ESCAPES[c] ?? c);
}

/**
 * 印刷用の商品カードを HTML 文字列にする（依存を使わない自作版）。
 * 値は必ず escapeHtml を通してから埋め込む。通さないと商品名に仕込まれたタグが実行される。
 */
export function printCardHtml(product: Product): string {
  return (
    '<article class="print-card">' +
    `<h2>${escapeHtml(product.name)}</h2>` +
    `<p>${escapeHtml(`${product.price} 円`)}</p>` +
    `<p>${escapeHtml(product.category)}</p>` +
    '</article>'
  );
}
