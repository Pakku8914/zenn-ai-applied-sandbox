// 商品名は変わらないので const
const productName = 'マグカップ';
// 在庫は売れるたびに変わるので let
let stock = 12;

console.log(productName + 'の在庫: ' + stock);

// 1個売れたので在庫を書き換える（これを「再代入」と呼ぶ）
stock = 11;

console.log('1個売れました');
console.log(productName + 'の在庫: ' + stock);
