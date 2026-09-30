import type { Page } from 'playwright';
import { collectVitals, interactAndCollect, latestPerName, median, withPage } from '../vitals-client.ts';
import type { Evidence } from './diagnose.ts';

/**
 * 横断復習②：「入力すると固まる」ページで、原因を切り分ける証拠を集める。
 * ファイル名が verify で始まらないので verify-all.sh からは直接実行されない。
 */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
export const KEYWORD = '商品1';
export const RUNS = 3;
/** web-vitals は既定で 40ms 未満の操作を INP の候補にしない */
export const INP_REPORT_THRESHOLD_MS = 40;

export type Subject = { name: string; total: number; matched: number };

/** 調べる4ページ。s08-bad-2k は「原因は見えるが直す必要がない」比較対象 */
export const SUBJECTS: Subject[] = [
  { name: 'r02-freeze-a', total: 20_000, matched: 11_111 },
  { name: 'r02-freeze-b', total: 2_000, matched: 1_111 },
  { name: 'r02-freeze-c', total: 2_000, matched: 1_111 },
  { name: 's08-bad-2k', total: 2_000, matched: 1_111 },
];

export type Observation = Evidence & {
  /** 入力後の一覧の行数（DOM） */
  liAfter: number;
  /** 入力中に記録された長いアニメーションフレーム（LoAF）の合計時間 */
  longFrameMs: number;
  /** そのうち、スクリプトが強制したスタイル計算とレイアウトの合計時間 */
  forcedLayoutMs: number;
};

type FrameSummary = { duration: number; forcedLayout: number };

async function readRowCount(page: Page): Promise<number> {
  return page.evaluate(
    () => (window as unknown as { __s08RenderCount?: Record<string, number> }).__s08RenderCount?.row ?? 0,
  );
}

/** LCP を取ってから #keyword に「商品1」を入力し、INP・行の実行回数・レイアウト回数・長いフレームを集める */
export async function observeTyping(page: Page, url: string, expectedLi: number): Promise<Observation> {
  // S03：入力より先に LCP を取る（先に入力すると LCP が永久に取れない）
  await collectVitals(page, url);

  // S06：レイアウトの回数は CDP の LayoutCount の前後差で数える（計測条件には触れない）
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const layoutCount = async (): Promise<number> => {
    const { metrics } = await cdp.send('Performance.getMetrics');
    return metrics.find((m) => m.name === 'LayoutCount')?.value ?? Number.NaN;
  };

  // S07：入力中の長いアニメーションフレームを記録する
  await page.evaluate(() => {
    const frames: { duration: number; forcedLayout: number }[] = [];
    (window as unknown as { __r02Frames: typeof frames }).__r02Frames = frames;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const scripts = (entry as unknown as { scripts?: { forcedStyleAndLayoutDuration?: number }[] }).scripts ?? [];
        frames.push({
          duration: entry.duration,
          forcedLayout: scripts.reduce((sum, s) => sum + (s.forcedStyleAndLayoutDuration ?? 0), 0),
        });
      }
    }).observe({ type: 'long-animation-frame', buffered: false });
  });

  const rowsBefore = await readRowCount(page);
  const layoutsBefore = await layoutCount();

  // S03：page.fill() ではなく実際のキー入力で INP を発生させる
  await interactAndCollect(page, '#keyword', KEYWORD);
  await page.waitForFunction((n) => document.querySelectorAll('section ul li').length === n, expectedLi, {
    timeout: 15_000,
  });

  const layoutsAfter = await layoutCount();
  const rowsAfter = await readRowCount(page);
  await page.waitForTimeout(500);

  const frames = await page.evaluate(
    () => (window as unknown as { __r02Frames?: FrameSummary[] }).__r02Frames ?? [],
  );
  const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));

  return {
    inputs: KEYWORD.length,
    inpMs: vitals.find((v) => v.name === 'INP')?.value ?? null,
    rowRenders: rowsAfter - rowsBefore,
    layouts: layoutsAfter - layoutsBefore,
    liAfter: await page.locator('section ul li').count(),
    longFrameMs: frames.reduce((sum, f) => sum + f.duration, 0),
    forcedLayoutMs: frames.reduce((sum, f) => sum + f.forcedLayout, 0),
  };
}

export type Summary = { subject: Subject; median: Evidence & { longFrameMs: number; forcedLayoutMs: number }; runs: Observation[] };

/** 毎回新しいブラウザで RUNS 回ずつ計測し、ページごとに中央値をまとめる（S03） */
export async function observeSubjects(): Promise<Summary[]> {
  const out: Summary[] = [];
  for (const subject of SUBJECTS) {
    const runs: Observation[] = [];
    for (let i = 0; i < RUNS; i += 1) {
      runs.push(await withPage((page) => observeTyping(page, `${TARGET}/pages/${subject.name}/`, subject.matched)));
    }
    const pick = (f: (o: Observation) => number): number => median(runs.map(f));
    out.push({
      subject,
      median: {
        inputs: KEYWORD.length,
        // 40ms 未満で報告されなかった回は、上限の 40ms として数える
        inpMs: pick((o) => o.inpMs ?? INP_REPORT_THRESHOLD_MS),
        rowRenders: pick((o) => o.rowRenders),
        layouts: pick((o) => o.layouts),
        longFrameMs: pick((o) => o.longFrameMs),
        forcedLayoutMs: pick((o) => o.forcedLayoutMs),
      },
      runs,
    });
  }
  return out;
}

export const ms = (v: number | null): string => (v === null ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`);
export const n = (v: number): string => Math.round(v).toLocaleString('en-US');

/** 証拠の表（判定は含めない。問題5で読者が判定する） */
export function evidenceRows(summaries: Summary[]): Record<string, string>[] {
  return summaries.map(({ subject, median: m }) => ({
    ページ: subject.name,
    件数: n(subject.total),
    '入力 INP': ms(m.inpMs),
    行の実行: n(m.rowRenders),
    レイアウト回数: n(m.layouts),
    長いフレーム: ms(m.longFrameMs),
    うち強制レイアウト: ms(m.forcedLayoutMs),
  }));
}
