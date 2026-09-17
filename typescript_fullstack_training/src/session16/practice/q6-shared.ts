// 問題6：循環参照を断ち切るために作った「誰も import しないファイル」。
// 型と、両方のファイルが使う定数だけを置く。

export type OrderLine = { productId: number; name: string; unitPrice: number; quantity: number };

export type Order = { id: number; lines: readonly OrderLine[] };

export const ORDER_LABEL = '注文';
