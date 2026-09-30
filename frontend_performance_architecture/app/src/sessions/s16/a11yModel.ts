/**
 * S16：アクセシビリティの判断を DOM から切り離した純粋関数。
 * 「どのキーで何番目へ動くか」「何を読み上げるか」「どの行を DOM に残すか」を vitest（環境 node）で固定する。
 */

export const CATEGORY_OPTIONS = ['すべて', '文具', '書籍', '雑貨', '食品'] as const;
export type CategoryOption = (typeof CATEGORY_OPTIONS)[number];

const countFormat = new Intl.NumberFormat('ja-JP');

/** 件数を 3 桁区切りにする（2000 → "2,000"） */
export function formatCount(count: number): string {
  return countFormat.format(count);
}

export const LOADING_MESSAGE = '商品を読み込んでいます';
export const NO_MATCH_MESSAGE =
  '条件に一致する商品はありません。キーワードを短くするか、カテゴリを「すべて」に戻してください。';

/** ライブリージョン（role="status"）に入れる文。何が起きたか＋必要なら次に何をするか */
export function resultMessage(count: number, total: number, filtered: boolean): string {
  if (!filtered) return `全 ${formatCount(total)} 件を表示しています`;
  if (count === 0) return NO_MATCH_MESSAGE;
  return `${formatCount(count)} 件見つかりました`;
}

/** 読み込み失敗（role="alert"）の文。原因の手がかりと、次の操作を必ず含める */
export function loadErrorMessage(status: number): string {
  return `商品を読み込めませんでした（${status}）。通信状態を確認して「もう一度読み込む」を押してください。`;
}

/** お気に入りの保存失敗（role="alert"）の文 */
export function saveErrorMessage(productName: string): string {
  return `${productName} をお気に入りに保存できませんでした。通信状態を確認して、もう一度押してください。`;
}

export type NavOptions = {
  /** 縦並びなら ↑↓、横並びなら ←→ で動く */
  orientation: 'horizontal' | 'vertical';
  /** 端で反対側へ回り込むか（ラジオグループは回り込む・一覧は回り込まない） */
  wrap: boolean;
};

/**
 * ロービングタブインデックスの移動先。扱わないキーなら null（呼び出し側は preventDefault しない）。
 */
export function nextIndex(current: number, key: string, count: number, { orientation, wrap }: NavOptions): number | null {
  if (count === 0) return null;
  const prevKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
  const nextKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
  switch (key) {
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    case nextKey:
      return current + 1 < count ? current + 1 : wrap ? 0 : current;
    case prevKey:
      return current > 0 ? current - 1 : wrap ? count - 1 : current;
    default:
      return null;
  }
}

/**
 * 仮想化した一覧で DOM に置く行の番号。表示範囲 [start, end) に、フォーカス中の行（pinned）を必ず加える。
 * 番号順に並べるので、DOM の順序（＝読み上げと Tab の順序）が見た目の順序と食い違わない。
 */
export function renderIndices(start: number, end: number, pinned: number | null): number[] {
  const indices: number[] = [];
  for (let i = start; i < end; i += 1) indices.push(i);
  if (pinned !== null && (pinned < start || pinned >= end)) {
    indices.push(pinned);
    indices.sort((a, b) => a - b);
  }
  return indices;
}

/** index 行目が表示枠に収まる scrollTop。すでに見えていれば今の値をそのまま返す */
export function scrollTopToReveal(index: number, scrollTop: number, rowHeight: number, viewportHeight: number): number {
  const top = index * rowHeight;
  const bottom = top + rowHeight;
  if (top < scrollTop) return top;
  if (bottom > scrollTop + viewportHeight) return bottom - viewportHeight;
  return scrollTop;
}
