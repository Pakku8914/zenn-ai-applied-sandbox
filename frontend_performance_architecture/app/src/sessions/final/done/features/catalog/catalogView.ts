import type { Product } from '../../../../../data/products';
import { resultMessage } from '../../../../s16/a11yModel';

/** 読み上げ（ライブリージョン）を、最後の入力からこの時間だけ待って 1 回にまとめる */
export const LIVE_DELAY_MS = 500;

/** 商品名にキーワードを含むものだけを残す。規則は出発点の ProductList と同じ */
export function filterByKeyword(items: readonly Product[], keyword: string): readonly Product[] {
  return keyword === '' ? items : items.filter((p) => p.name.includes(keyword));
}

/** 一覧の見出し。計測スクリプトは「（N 件）」の部分で件数を読むので、この書式は変えない */
export function countHeading(count: number): string {
  return `商品一覧（${count} 件）`;
}

/** ライブリージョンに入れる文（S16 の resultMessage をそのまま使う） */
export function statusMessage(count: number, total: number, keyword: string): string {
  return resultMessage(count, total, keyword !== '');
}
