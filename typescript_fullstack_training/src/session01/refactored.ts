// 練習問題7の解答。ミニ雑貨ショップの商品1件の情報。

// 商品名
const productName = 'タオル';
// 価格（円・整数）
const price = 980;
// 在庫数（個）
const stock = 5;
// セール中かどうか
const isOnSale = true;
// 販売終了のお知らせ文。意図して「無し」と設定されている
const discontinuedNote: null = null;

console.log(productName, price, stock, isOnSale, discontinuedNote);
console.log(productName + 'は' + price + '円です');
