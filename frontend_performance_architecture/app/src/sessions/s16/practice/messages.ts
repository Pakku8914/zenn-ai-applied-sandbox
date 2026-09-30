import { formatCount, type CategoryOption } from '../a11yModel';

/**
 * 問題2：件数だけでなく「どの条件で」絞り込んだかも読み上げる文。
 * 画面を見ていない利用者は、いまの条件を目で確かめられないため。
 */
export function conditionMessage(count: number, total: number, keyword: string, category: CategoryOption): string {
  const conditions = [category === 'すべて' ? null : `カテゴリ「${category}」`, keyword === '' ? null : `「${keyword}」`].filter(
    (c): c is string => c !== null,
  );
  if (conditions.length === 0) return `全 ${formatCount(total)} 件を表示しています`;
  const label = conditions.join('・');
  if (count === 0) return `${label}に一致する商品はありません。条件を減らしてください。`;
  return `${label}で ${formatCount(count)} 件見つかりました`;
}
