import { animateCart, type AnimationKind, type FrameReport } from '../animate';
import {
  collectRows,
  drawBarsBatched,
  drawBarsThrashing,
  editStock,
  markNarrowPhased,
  markNarrowThrashing,
  resetBars,
} from '../bar-rows';

/**
 * 計測用に window.__s06Lab として公開する実験の入口。
 * measure/src/session06/lab.ts が page.evaluate からこれを呼ぶ（名前と戻り値の形を変えない）。
 */
export type LabApi = {
  drawBars(mode: 'thrashing' | 'batched'): number;
  markNarrow(mode: 'thrashing' | 'phased'): number;
  editStock(contained: boolean, times: number): { ms: number; contain: string };
  animate(kind: AnimationKind, durationMs: number): Promise<FrameReport>;
  snapshot(): { rows: number; barWidthSum: number; narrowCount: number };
};

declare global {
  interface Window {
    __s06Lab?: LabApi;
  }
}

export function createLab(list: HTMLElement, panel: HTMLElement): LabApi {
  const rows = collectRows(list);

  /** 前の状態をそろえてから work の所要時間を測る。最後の読み取りで、保留中のレイアウトも所要時間に含める */
  const timed = (work: () => void): number => {
    resetBars(rows);
    void list.offsetHeight;
    const start = performance.now();
    work();
    void list.offsetHeight;
    return performance.now() - start;
  };

  return {
    drawBars: (mode) => timed(() => (mode === 'thrashing' ? drawBarsThrashing(rows) : drawBarsBatched(rows))),
    markNarrow: (mode) => timed(() => (mode === 'thrashing' ? markNarrowThrashing(rows) : markNarrowPhased(rows))),
    editStock: (contained, times) => {
      list.classList.toggle('contained', contained);
      void list.offsetHeight;
      const start = performance.now();
      editStock(rows, times);
      const ms = performance.now() - start;
      const first = rows[0];
      return { ms, contain: first ? getComputedStyle(first.row).contain : '' };
    },
    animate: (kind, durationMs) => animateCart(kind, list, panel, durationMs),
    snapshot: () => ({
      rows: rows.length,
      barWidthSum: rows.reduce((sum, { bar }) => sum + Number.parseFloat(bar.style.width || '0'), 0),
      narrowCount: rows.filter(({ bar }) => bar.classList.contains('narrow')).length,
    }),
  };
}
