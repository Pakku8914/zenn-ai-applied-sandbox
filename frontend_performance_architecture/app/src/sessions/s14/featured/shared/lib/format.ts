/** 金額を「1,234 円」の形にする。UI も業務の知識も持たない道具なので、どの feature からも使える */
export function formatYen(amount: number): string {
  return `${amount.toLocaleString('ja-JP')} 円`;
}
