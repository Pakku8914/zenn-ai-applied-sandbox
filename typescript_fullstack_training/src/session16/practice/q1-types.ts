// 問題1：型だけを置くファイル。
export type StockItem = { id: number; name: string; price: number; stock: number };

export type StockReport = {
  totalValue: number;
  soldOutNames: readonly string[];
  lowStockNames: readonly string[];
};
