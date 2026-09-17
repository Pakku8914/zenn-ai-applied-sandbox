// ミニ雑貨ショップのレシート1件を計算する。
// 本書のルール：金額はすべて整数（円）で扱う。
// 期待される出力の検証は同じフォルダの verify.ts が行う。

const TAX_RATE = 0.1; // 消費税率10%
const SHIPPING_FEE = 500; // 送料（円）
const FREE_SHIPPING_THRESHOLD = 3000; // この金額以上で送料無料（円）

const productName = 'ハンドクリーム';
const unitPrice = 1800; // 税抜価格（円・整数）
const quantity = 2;

const subtotal = unitPrice * quantity; // 税抜の商品合計
const totalWithTax = Math.floor(subtotal * (1 + TAX_RATE)); // 税込（端数は切り捨て）
const isFreeShipping = totalWithTax >= FREE_SHIPPING_THRESHOLD;
const remainingForFree = Math.max(0, FREE_SHIPPING_THRESHOLD - totalWithTax);

console.log(`商品：${productName}`);
console.log(`単価：${unitPrice}円 × ${quantity}点 = ${subtotal}円`);
console.log(`税込：${totalWithTax}円`);
console.log(`送料無料：${isFreeShipping}`);
console.log(`送料無料まで：あと${remainingForFree}円`);
console.log(`（送料無料でない場合の送料：${SHIPPING_FEE}円）`);
