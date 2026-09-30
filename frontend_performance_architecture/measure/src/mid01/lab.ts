import type { Page } from 'playwright';
import { CONDITIONS, collectVitals, interactAndCollect, latestPerName, withPage } from '../vitals-client.ts';

/**
 * 中間プロジェクトの計測で共通に使う道具。ファイル名が verify で始まらないので verify-all.sh からは直接実行されない。
 * 使ってよいのは ../vitals-client.ts の API だけ（計測条件 CONDITIONS には触れない）。
 */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';

/** ページ名から URL を作る。root は出発点（ルートの index.html） */
export const pageUrl = (name: string): string => (name === 'root' ? `${TARGET}/` : `${TARGET}/pages/${name}/`);

export const KEYWORD = '商品1';
/** 「商品1」を含む商品の数（商品1・10〜19・100〜199・1000〜1999） */
export const MATCHED = 1_111;
/** web-vitals は既定で 40ms 未満の操作を INP の候補にしない */
export const INP_REPORT_THRESHOLD_MS = 40;

// app/src/sessions/mid01 と同じ値（measure から app のコードは import できないため写している）
export const PAGE_TAG_MS = 300;
export const SEARCH_LOG_MS = 250;
export const SEARCH_LOG_DEBOUNCE_MS = 500;

declare global {
  interface Window {
    __mid01?: { searchLogs: string[] };
    __mid01Events?: number[];
  }
}

/** 本文に数値を載せるときに必ず添える計測条件の表記 */
export function conditionsLabel(): string {
  const { cpuThrottlingRate, network } = CONDITIONS;
  return `CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド`;
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

export const ms = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v) ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`;
export const n = (v: number): string => v.toLocaleString('en-US');

export type LcpInfo = { tag: string; className: string; size: number };

/** LCP 要素を調べる。LCP エントリは buffered: true の PerformanceObserver でしか取れない */
export async function lcpElement(page: Page): Promise<LcpInfo> {
  return page.evaluate(
    () =>
      new Promise<LcpInfo>((resolve) => {
        new PerformanceObserver((list) => {
          const last = list.getEntries().at(-1) as (PerformanceEntry & { element?: Element | null; size?: number }) | undefined;
          resolve({
            tag: last?.element?.nodeName ?? '（不明）',
            className: last?.element?.getAttribute('class') ?? '',
            size: last?.size ?? 0,
          });
        }).observe({ type: 'largest-contentful-paint', buffered: true });
        setTimeout(() => resolve({ tag: '（なし）', className: '', size: 0 }), 2_000);
      }),
  );
}

/**
 * CLS を 1 回計測する。バナーは LCP の後に差し込まれるので、LCP の報告直後に読むとずれを取りこぼす。
 * バナー（data-campaign="loaded"）の表示を待ち、layout-shift の報告が届くまで少し待ってから読む。入力はしない。
 */
export async function clsOnce(url: string): Promise<number> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    // バナーの無いページ（出発点など）では待ちきって先へ進む
    await page.waitForSelector('[data-campaign="loaded"]', { timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(500);
    const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
    return vitals.find((v) => v.name === 'CLS')?.value ?? 0; // ずれが一度もなければ CLS は報告されない＝0
  });
}

export type Shift = { value: number; sources: string[] };

/** layout-shift エントリの sources から「どの要素が・どこからどこへ」動いたかを読む */
export async function shiftSources(url: string): Promise<Shift[]> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    await page.waitForSelector('[data-campaign="loaded"]', { timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(500);
    return page.evaluate(
      () =>
        new Promise<Shift[]>((resolve) => {
          new PerformanceObserver((list) => {
            resolve(
              list.getEntries().map((entry) => {
                const shift = entry as PerformanceEntry & {
                  value: number;
                  sources?: { node?: Node | null; previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly }[];
                };
                return {
                  value: Math.round(shift.value * 1000) / 1000,
                  sources: (shift.sources ?? []).map(
                    (s) => `${s.node?.nodeName ?? '（削除済み）'} y=${Math.round(s.previousRect.y)}→${Math.round(s.currentRect.y)}`,
                  ),
                };
              }),
            );
          }).observe({ type: 'layout-shift', buffered: true });
          setTimeout(() => resolve([]), 1_000); // ずれが一度もなければ observer は呼ばれない
        }),
    );
  });
}

export type TypingRun = {
  /** web-vitals が報告した INP。40ms 未満の操作は観測されず null になる */
  inp: number | null;
  /** 入力中のキー・input イベントのうち、最も長い「処理時間」（processingEnd − processingStart） */
  maxProcessing: number;
  /** ページが送った検索ログ（キーワードの並び） */
  searchLogs: string[];
  /** 入力後の一覧の行数 */
  liAfter: number;
};

/**
 * LCP を取ってから #keyword に「商品1」を入力し、INP の内訳（処理時間）と検索ログの送信回数を集める。
 * どの区間が長いかを見るための診断用。INP の中央値は measureMedian で別に取る。
 */
export async function typingRun(url: string): Promise<TypingRun> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    await page.evaluate(() => {
      const rec: number[] = [];
      window.__mid01Events = rec;
      new PerformanceObserver((list) => {
        for (const e of list.getEntries() as PerformanceEventTiming[]) {
          if (['keydown', 'keypress', 'input', 'keyup'].includes(e.name)) rec.push(e.processingEnd - e.processingStart);
        }
      }).observe({ type: 'event', durationThreshold: 16, buffered: false } as PerformanceObserverInit);
    });
    const vitals = await interactAndCollect(page, '#keyword', KEYWORD);
    // デバウンスした版は、入力が止まってから送信するので、その分も待つ
    await page.waitForTimeout(SEARCH_LOG_DEBOUNCE_MS + SEARCH_LOG_MS + 500);
    const raw = await page.evaluate(() => ({
      events: window.__mid01Events ?? [],
      searchLogs: window.__mid01?.searchLogs ?? [],
      liAfter: document.querySelectorAll('section ul li').length,
    }));
    return {
      inp: vitals.find((v) => v.name === 'INP')?.value ?? null,
      maxProcessing: raw.events.length === 0 ? 0 : Math.max(...raw.events),
      searchLogs: raw.searchLogs,
      liAfter: raw.liAfter,
    };
  });
}

/** LCP を取ってから「グラフを表示」ボタンをクリックし、そのクリックの INP を返す（40ms 未満は null） */
export async function chartClickInp(url: string): Promise<number | null> {
  return withPage(async (page) => {
    // 先にクリックすると web-vitals が LCP の観測を打ち切るので、必ず LCP の取得を先にする
    await collectVitals(page, url);
    await page.getByRole('button', { name: 'グラフを表示' }).click();
    await page.locator('figure').waitFor({ timeout: 15_000 });
    await page.waitForTimeout(800);
    const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
    return vitals.find((v) => v.name === 'INP')?.value ?? null;
  });
}
