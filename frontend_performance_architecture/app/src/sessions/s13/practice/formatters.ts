// 見た目は似ているが、変わる理由が違う3つ。1つにまとめず別々の関数にしておく

/** 商品の価格。表示は税込であることを明記する（仕様変更後） */
export function formatPrice(price: number): string {
  return `${price.toLocaleString('ja-JP')} 円（税込）`;
}

/** 送料。0 円のときは「送料無料」と出す */
export function formatShippingFee(fee: number): string {
  return fee === 0 ? '送料無料' : `送料 ${fee.toLocaleString('ja-JP')} 円`;
}

/** ポイント。単位は円ではない */
export function formatPoints(points: number): string {
  return `${points.toLocaleString('ja-JP')} pt`;
}
