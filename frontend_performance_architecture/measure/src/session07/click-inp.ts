import type { Page } from 'playwright';
import { collectVitals, latestPerName, type Vital } from '../vitals-client.ts';

/**
 * S07 用：「グラフを表示」ボタンをクリックし、そのクリックの INP と周辺の記録を集める。
 * interactAndCollect は入力欄（pressSequentially）用なので、クリック用をここに書く。
 */
export type LongFrame = {
  type: string;
  startTime: number;
  duration: number;
  blockingDuration: number | null;
  invokers: string[];
};

/** Event Timing API が報告した click の内訳（すべて ms） */
export type Breakdown = { inputDelay: number; processing: number; presentation: number; duration: number };

export type ClickRun = {
  /** web-vitals が報告した INP。40ms 未満の操作は観測されず null になる */
  inp: number | null;
  inpRating: string | null;
  breakdown: Breakdown | null;
  polyline: string;
  /** figure[data-state] の移り変わり（出発点は data-state を持たないので空） */
  states: string[];
  /** クリックから点列が DOM に入るまで */
  readyMs: number;
  chunks: number | null;
  yieldStrategy: string | null;
  /** クリック以降に記録された長いフレーム */
  frames: LongFrame[];
};

declare global {
  interface Window {
    __longFrames?: LongFrame[];
    __s07?: { clickAt: number | null; readyAt: number | null; states: string[]; events: Breakdown[] };
  }
}

/** web-vitals は既定で 40ms 未満の操作を INP の候補にしない（durationThreshold） */
export const INP_REPORT_THRESHOLD_MS = 40;

/** クリック前に、状態の移り変わり・click の Event Timing を記録する仕掛けを入れる */
export async function installRecorders(page: Page): Promise<void> {
  await page.evaluate(() => {
    const rec = { clickAt: null as number | null, readyAt: null as number | null, states: [] as string[], events: [] as Breakdown[] };
    window.__s07 = rec;

    document.addEventListener('click', (e) => (rec.clickAt ??= e.timeStamp), { capture: true });

    new MutationObserver(() => {
      const state = document.querySelector('figure[data-state]')?.getAttribute('data-state');
      if (state && rec.states.at(-1) !== state) rec.states.push(state);
      if (rec.readyAt === null && document.querySelector('figure polyline')) rec.readyAt = performance.now();
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state'] });

    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as PerformanceEventTiming[]) {
        if (e.name !== 'click') continue;
        rec.events.push({
          inputDelay: e.processingStart - e.startTime,
          processing: e.processingEnd - e.processingStart,
          presentation: e.startTime + e.duration - e.processingEnd,
          duration: e.duration,
        });
      }
    }).observe({ type: 'event', durationThreshold: 16, buffered: false } as PerformanceObserverInit);
  });
}

/** 記録を読み出して ClickRun にまとめる */
export async function readRun(page: Page): Promise<ClickRun> {
  const raw = await page.evaluate(() => {
    const rec = window.__s07!;
    const figure = document.querySelector('figure');
    return {
      vitals: window.__webVitals ?? [],
      clickAt: rec.clickAt ?? 0,
      readyAt: rec.readyAt ?? Number.NaN,
      states: rec.states,
      events: rec.events,
      polyline: document.querySelector('figure polyline')?.getAttribute('points') ?? '',
      chunks: figure?.getAttribute('data-chunks') ?? null,
      yieldStrategy: figure?.getAttribute('data-yield') ?? null,
      frames: window.__longFrames ?? [],
    };
  });
  const inp: Vital | undefined = latestPerName(raw.vitals).find((v) => v.name === 'INP');
  const longest = [...raw.events].sort((a, b) => b.duration - a.duration)[0] ?? null;
  return {
    inp: inp?.value ?? null,
    inpRating: inp?.rating ?? null,
    breakdown: longest,
    polyline: raw.polyline,
    states: raw.states,
    readyMs: raw.readyAt - raw.clickAt,
    chunks: raw.chunks === null ? null : Number(raw.chunks),
    yieldStrategy: raw.yieldStrategy,
    frames: raw.frames.filter((f) => f.startTime + f.duration >= raw.clickAt),
  };
}

/** LCP を取ってからボタンをクリックし、点列が出るのを待って記録を返す */
export async function clickAndCollect(page: Page, url: string, settleMs = 2_000): Promise<ClickRun> {
  // 先にクリックすると web-vitals が LCP の観測を打ち切るので、必ず LCP の取得を先にする
  await collectVitals(page, url);
  await installRecorders(page);
  await page.click('button');
  await page.locator('figure polyline').waitFor({ timeout: 15_000 });
  // INP は次の描画のあとに報告されるので、少し待ってから読む
  await page.waitForTimeout(settleMs);
  return readRun(page);
}

export const ms = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v) ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`;
