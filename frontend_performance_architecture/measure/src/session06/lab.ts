import type { Page } from 'playwright';
import { CONDITIONS, collectVitals } from '../vitals-client.ts';

/** 本文に数値を載せるときに必ず添える計測条件の表記 */
export function conditionsLabel(): string {
  const { cpuThrottlingRate, network } = CONDITIONS;
  return `CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド`;
}

/**
 * S06 の検証で共通に使う道具。ファイル名が verify で始まらないので verify-all.sh からは直接実行されない。
 */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
export const LAB_URL = `${TARGET}/pages/s06-layout-lab/`;

/** app/src/sessions/s06/lab/lab-api.ts の LabApi と同じ形（ページ側が window に公開する） */
type LabApi = {
  drawBars(mode: 'thrashing' | 'batched'): number;
  markNarrow(mode: 'thrashing' | 'phased'): number;
  editStock(contained: boolean, times: number): { ms: number; contain: string };
  animate(
    kind: 'width' | 'transform' | 'settle',
    durationMs: number,
  ): Promise<{ frames: number; averageIntervalMs: number; slowFrames: number }>;
  snapshot(): { rows: number; barWidthSum: number; narrowCount: number };
};

declare global {
  interface Window {
    __s06Lab?: LabApi;
  }
}

/** 実験台を開き、LCP の報告と実験用 API の公開を待つ */
export async function openLab(page: Page): Promise<void> {
  await collectVitals(page, LAB_URL);
  await page.waitForFunction(() => window.__s06Lab !== undefined);
}

/**
 * Chrome が数えているレイアウトの実行回数（CDP の Performance.getMetrics の LayoutCount）を読む関数を返す。
 * 計測条件（CONDITIONS）には触れず、値を読むだけ。前後の差がその操作で起きたレイアウトの回数になる。
 */
export async function layoutCounter(page: Page): Promise<() => Promise<number>> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  return async () => {
    const { metrics } = await cdp.send('Performance.getMetrics');
    return metrics.find((m) => m.name === 'LayoutCount')?.value ?? Number.NaN;
  };
}

export function createChecker(): { check: (name: string, ok: boolean, detail?: string) => void; finish: (label: string) => void } {
  const failures: string[] = [];
  return {
    check(name, ok, detail = '') {
      console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
      if (!ok) failures.push(name);
    },
    finish(label) {
      if (failures.length > 0) {
        console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
        process.exit(1);
      }
      console.log(`\n${label}の検証に成功しました。`);
    },
  };
}

export const ms1 = (v: number): string => `${(Math.round(v * 10) / 10).toLocaleString('en-US')}ms`;
