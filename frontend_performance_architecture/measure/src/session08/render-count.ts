import type { Page } from 'playwright';
import { collectVitals, interactAndCollect, latestPerName } from '../vitals-client.ts';

/**
 * S08 用：ページ側の手動カウンタ（window.__s08RenderCount）を読む補助。
 * 本番ビルドでは <Profiler> の onRender が呼ばれないため、再レンダリング回数はこのカウンタで数える。
 */
export type Counts = Record<string, number>;

declare global {
  interface Window {
    __s08RenderCount?: Counts;
  }
}

export async function readCounts(page: Page): Promise<Counts> {
  return page.evaluate(() => ({ ...(window.__s08RenderCount ?? {}) }));
}

/** after − before を名前ごとに出す（片方にしか無い名前は 0 として扱う） */
export function diffCounts(before: Counts, after: Counts): Counts {
  const names = new Set([...Object.keys(before), ...Object.keys(after)]);
  const out: Counts = {};
  for (const name of names) out[name] = (after[name] ?? 0) - (before[name] ?? 0);
  return out;
}

export type TypingRun = {
  /** web-vitals が報告した INP。40ms 未満の操作は観測されず null になる */
  inp: number | null;
  /** 最初の表示までに実行された行の数 */
  rowsOnMount: number;
  /** 「商品1」を入力している間に実行された行の数 */
  rowsWhileTyping: number;
  /** 入力後、1行目 → 2行目の順にクリックして選んだ間に実行された行の数 */
  rowsWhileSelecting: number;
  /** 同じく、行を2回選ぶ間にカタログ（親）の本体が実行された回数 */
  catalogWhileSelecting: number;
  /** 入力後の一覧の行数（DOM） */
  liAfter: number;
};

export const KEYWORD = '商品1';

/**
 * LCP を取ってから #keyword に「商品1」を入力し、INP と再レンダリング回数を集める。
 * そのあと行を2回クリックして、選択による再レンダリング回数も数える（INP は先に読んでおく）。
 */
export async function typeAndCount(page: Page, url: string, expectedLi: number): Promise<TypingRun> {
  await collectVitals(page, url);
  const mounted = await readCounts(page);

  await interactAndCollect(page, '#keyword', KEYWORD);
  // useDeferredValue / useTransition の版は一覧が遅れて追いつくので、行数がそろうまで待つ
  await page.waitForFunction((n) => document.querySelectorAll('section ul li').length === n, expectedLi, {
    timeout: 15_000,
  });
  await page.waitForTimeout(500);
  const typed = await readCounts(page);
  const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
  const inp = vitals.find((v) => v.name === 'INP')?.value ?? null;

  await page.click('section ul li:nth-child(1)');
  await page.locator('section ul li:nth-child(1)[data-selected="true"]').waitFor();
  await page.click('section ul li:nth-child(2)');
  await page.locator('section ul li:nth-child(2)[data-selected="true"]').waitFor();
  const selected = await readCounts(page);

  return {
    inp,
    rowsOnMount: mounted.row ?? 0,
    rowsWhileTyping: diffCounts(mounted, typed).row ?? 0,
    rowsWhileSelecting: diffCounts(typed, selected).row ?? 0,
    catalogWhileSelecting: diffCounts(typed, selected).catalog ?? 0,
    liAfter: await page.locator('section ul li').count(),
  };
}

/** web-vitals は既定で 40ms 未満の操作を INP の候補にしない */
export const INP_REPORT_THRESHOLD_MS = 40;

export const ms = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v) ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`;

export const n = (v: number): string => v.toLocaleString('en-US');
