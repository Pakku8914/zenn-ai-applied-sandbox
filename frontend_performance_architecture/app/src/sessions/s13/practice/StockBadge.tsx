import { assertNever } from '../../s10/requestState';

/** 在庫の表示。few のときだけ残り数を持つ（「残り数の無い few」を作れない） */
export type StockStatus = { kind: 'inStock' } | { kind: 'few'; remaining: number } | { kind: 'soldOut' };

/** 残り数を5点以下で「残りわずか」とする。判定は表示部品の外に置く */
export const FEW_THRESHOLD = 5;

export function toStockStatus(remaining: number): StockStatus {
  if (remaining <= 0) return { kind: 'soldOut' };
  if (remaining <= FEW_THRESHOLD) return { kind: 'few', remaining };
  return { kind: 'inStock' };
}

export function StockBadge({ status }: { status: StockStatus }) {
  switch (status.kind) {
    case 'inStock':
      return <span className="stock">在庫あり</span>;
    case 'few':
      return <span className="stock stock-few">残り{status.remaining}点</span>;
    case 'soldOut':
      return <span className="stock stock-out">売り切れ</span>;
    default:
      return assertNever(status);
  }
}
