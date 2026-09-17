// 練習問題6の解答。var を使わない形に書き換えたもの。

// このコードでは後半で商品名も差し替えているので let
let productName = 'マグカップ';
// 価格は最後まで変わらないので const
const price = 1200;
// 在庫は後半で書き換わるので let
let stock = 12;

console.log(productName, price, stock);

// 2回目は「宣言」ではなく「代入」にする（var を外すだけでよい）
stock = 11;
productName = 'マグカップ（新パッケージ）';

console.log(productName, price, stock);
