// 練習問題3の解答。

// 商品名はこのプログラムの中で変わらないので const
const productName = 'タオル';
// 価格も変わらないので const
const price = 980;
// 在庫は売れるたびに書き換わるので let
let stock = 5;

console.log(productName + '（' + price + '円）の在庫:', stock, '個');

// 2個売れた（引き算は次章で扱うので、ここでは結果の値を直接代入する）
stock = 3;
console.log('2個売れました');
console.log(productName + '（' + price + '円）の在庫:', stock, '個');

// さらに3個売れた
stock = 0;
console.log('3個売れました');
console.log(productName + '（' + price + '円）の在庫:', stock, '個');
