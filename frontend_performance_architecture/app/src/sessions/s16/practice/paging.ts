import { ROW_HEIGHT, VIEWPORT_HEIGHT } from '../../s11/rows';
import { nextIndex } from '../a11yModel';

/** 表示枠 1 つぶんの行数（400 / 40 = 10） */
export const PAGE_SIZE = VIEWPORT_HEIGHT / ROW_HEIGHT;

/** 問題4：↑↓・Home・End に加えて、PageDown / PageUp で表示枠 1 つぶん移動する。端では止まる */
export function nextIndexWithPaging(current: number, key: string, count: number, pageSize: number = PAGE_SIZE): number | null {
  if (count === 0) return null;
  if (key === 'PageDown') return Math.min(count - 1, current + pageSize);
  if (key === 'PageUp') return Math.max(0, current - pageSize);
  return nextIndex(current, key, count, { orientation: 'vertical', wrap: false });
}
