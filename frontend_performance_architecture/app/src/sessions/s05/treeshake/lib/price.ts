export function formatPrice(yen: number): string {
  return `${new Intl.NumberFormat('ja-JP').format(yen)} 円`;
}
