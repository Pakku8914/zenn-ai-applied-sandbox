// 練習問題2の解答。
// パート1：型注釈を明示して宣言する（学習のための書き方）

// カテゴリ名
const categoryName: string = 'キッチン';
// 送料（円・整数）
const shippingFee: number = 500;
// 送料無料かどうか
const isFreeShipping: boolean = false;

console.log('カテゴリ:', categoryName);
console.log('送料:', shippingFee, '円');
console.log('送料無料:', isFreeShipping);

// パート2：宣言の時点では値を決められないので、型注釈が必要になる
let selectedProductName: string;
selectedProductName = 'ソックス';
console.log('選択中の商品:', selectedProductName);

// 代入する前に selectedProductName を使うと、次のエラーが報告される。
// error TS2454: Variable 'selectedProductName' is used before being assigned.
// 意味：まだ何も入っていない変数を読もうとしている。
