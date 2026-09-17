/**
 * 環境が正しく動くことを確認するテスト。
 * 期待値と一致しなければエラー終了する。
 */

// 1. 基本的な型注釈と文字列が動くこと
const greeting: string = 'Hello, TypeScript!';
if (greeting !== 'Hello, TypeScript!') {
  console.error(`文字列が期待値と異なります: ${greeting}`);
  process.exit(1);
}

// 2. 金額計算（本書は金額を整数の円で扱う）が動くこと
const TAX_RATE = 0.1;
const priceWithTax = Math.floor(1200 * (1 + TAX_RATE));
if (priceWithTax !== 1320) {
  console.error(`税込価格が期待値と異なります: ${priceWithTax}`);
  process.exit(1);
}

console.log('smoke: ok');
