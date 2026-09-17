// /products とその配下（/products/[id]）を表示している間に代わりに出る画面。
// ファイルを置くだけで有効になる。呼び出し側のコードは要らない。
export default function Loading() {
  return <p>商品を読み込んでいます…</p>;
}
