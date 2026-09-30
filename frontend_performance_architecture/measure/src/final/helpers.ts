import type { Page } from 'playwright';
import {
  CONDITIONS,
  collectVitals,
  interactAndCollect,
  latestPerName,
  measureMedian,
  median,
  withPage,
} from '../vitals-client.ts';

/**
 * 最終プロジェクトの計測で共有する定数と補助関数（verify*.ts ではないので verify-all.sh からは直接実行されない）。
 * 使うのは ../vitals-client.ts の API だけ。計測条件 CONDITIONS には触れない。
 *
 * 計測対象のページが守る「計測の契約」
 *   - 入力欄は #keyword、グラフのボタンは名前が「グラフを表示」の button、グラフは figure の中の polyline
 *   - 一覧の見出しは最初の section の h2 で、「（N 件）」の形で件数を書く
 *   - キャンペーンバナーは文言が届いたら data-campaign="loaded" になる
 */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
export const pageUrl = (name: string): string => `${TARGET}/pages/${name}/`;
export const START = pageUrl('final-start');
export const DONE = pageUrl('final-done');

export const TOTAL = 20_000;
export const KEYWORD = '商品1';
/** 「商品1」を含む件数（商品1・10〜19・100〜199・1000〜1999・10000〜19999） */
export const MATCHED = 11_111;
/** LCP・INP・初期 JS は 3 回、実行ごとに揺れやすい CLS は 5 回の中央値を採る */
export const RUNS = 3;
export const CLS_RUNS = 5;
/** web-vitals は既定で 40ms 未満の操作を INP の候補にしない。報告されなかった回は 40ms として数える */
export const INP_REPORT_THRESHOLD_MS = 40;

export const n = (v: number): string => v.toLocaleString('en-US');
export const ms = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v) ? 'なし' : `${Math.round(v).toLocaleString('en-US')}ms`;

export function conditionsLabel(): string {
  const { cpuThrottlingRate, network } = CONDITIONS;
  return `CPU ${cpuThrottlingRate}倍スロットリング / ${n(network.downloadKbps)}kbps / RTT ${network.latencyMs}ms / 本番ビルド`;
}

export function createChecker(): {
  check: (name: string, ok: boolean, detail?: string) => void;
  finish: (label: string) => void;
} {
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

/** 見出しが「（count 件）」になるまで待つ。全件描画のページは再レンダリングに時間がかかるので長めに待つ */
export async function waitForCount(page: Page, count: number): Promise<void> {
  await page.waitForFunction(
    (c) => document.querySelector('section h2')?.textContent?.includes(`（${c} 件）`) ?? false,
    count,
    { timeout: 30_000 },
  );
}

/** 待ちきれなければ false（直後の check で NG として報告する） */
export async function countReached(page: Page, count: number): Promise<boolean> {
  try {
    await waitForCount(page, count);
    return true;
  } catch {
    return false;
  }
}

/** バナーの文言が届くまで待つ。バナーは LCP の後に出るので、CLS と DOM の数はこれを待ってから読む */
export async function waitForBanner(page: Page): Promise<void> {
  await page.waitForSelector('[data-campaign="loaded"]', { timeout: 10_000 });
}

export type DomStats = {
  /** 一覧の行（section ul li）の数 */
  rows: number;
  /** React が描いた要素（#root *）の数 */
  nodes: number;
};

export const domStats = (page: Page): Promise<DomStats> =>
  page.evaluate(() => ({
    rows: document.querySelectorAll('section ul li').length,
    nodes: document.querySelectorAll('#root *').length,
  }));

async function vitalValue(page: Page, name: string): Promise<number | null> {
  const vitals = latestPerName(await page.evaluate(() => window.__webVitals ?? []));
  return vitals.find((v) => v.name === name)?.value ?? null;
}

/** LCP を取ってから #keyword に「商品1」をキー入力し、件数が変わりきるのを待って INP と DOM の数を読む */
export async function typingRun(url: string): Promise<{ inp: number | null; after: DomStats }> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    await waitForBanner(page);
    await interactAndCollect(page, '#keyword', KEYWORD);
    await waitForCount(page, MATCHED);
    await page.waitForTimeout(300); // INP の報告が web-vitals に届くのを待つ
    return { inp: await vitalValue(page, 'INP'), after: await domStats(page) };
  });
}

/** LCP を取ってから「グラフを表示」を押し、グラフが描き終わるのを待ってそのクリックの INP を読む（40ms 未満は null） */
export async function clickRun(url: string): Promise<number | null> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    await waitForBanner(page);
    // 出題版はボタンが 20,001 個あり、getByRole は全ボタンのアクセシブルネームを計算するため
    // CPU を絞った条件では 30 秒を超える。文言の完全一致で探す
    await page.locator('button:text-is("グラフを表示")').click();
    await page.locator('figure polyline').waitFor({ timeout: 20_000 });
    // 描画が重いページほど INP の報告が遅れて届く。固定時間ではなく報告を待つ（40ms 未満は報告されないので上限付き）
    await page
      .waitForFunction(() => (window.__webVitals ?? []).some((m) => m.name === 'INP'), undefined, { timeout: 5_000 })
      .catch(() => undefined);
    return vitalValue(page, 'INP');
  });
}

/** バナーの表示を待ってから CLS を読む（LCP の直後に読むと、後から起きるずれを取りこぼす）。ずれが無ければ 0 */
export async function clsOnce(url: string): Promise<number> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    await waitForBanner(page);
    await page.waitForTimeout(500);
    return (await vitalValue(page, 'CLS')) ?? 0;
  });
}

export type PageSummary = {
  lcp: number;
  jsBytes: number;
  jsRuns: number[];
  inputInp: number;
  inputUnreported: number;
  clickInp: number;
  clickUnreported: number;
  cls: number;
  /** 開いてバナーが出た直後 */
  opened: DomStats;
  /** 「商品1」を入力した後（各回） */
  typedRuns: DomStats[];
};

/** 1 ページぶんの基準値を、同じ条件でまとめて取る */
export async function measurePage(url: string): Promise<PageSummary> {
  const load = await measureMedian(url, { runs: RUNS }); // 入力なし：LCP と初期 JS
  const typing: { inp: number | null; after: DomStats }[] = [];
  for (let i = 0; i < RUNS; i += 1) typing.push(await typingRun(url));
  const clicks: (number | null)[] = [];
  for (let i = 0; i < RUNS; i += 1) clicks.push(await clickRun(url));
  const clsValues: number[] = [];
  for (let i = 0; i < CLS_RUNS; i += 1) clsValues.push(await clsOnce(url));
  const opened = await withPage(async (page) => {
    await collectVitals(page, url);
    await waitForBanner(page);
    return domStats(page);
  });

  return {
    lcp: load.median.LCP ?? Number.NaN,
    jsBytes: load.median.jsBytes ?? Number.NaN,
    jsRuns: load.runs.map((r) => r.jsBytes),
    inputInp: median(typing.map((t) => t.inp ?? INP_REPORT_THRESHOLD_MS)),
    inputUnreported: typing.filter((t) => t.inp === null).length,
    clickInp: median(clicks.map((c) => c ?? INP_REPORT_THRESHOLD_MS)),
    clickUnreported: clicks.filter((c) => c === null).length,
    cls: median(clsValues),
    opened,
    typedRuns: typing.map((t) => t.after),
  };
}

export const TABLE_HEADER = [
  '| ページ | LCP | 入力 INP | クリック INP | CLS | 初期 JS | DOM ノード（開いた直後 / 入力後） | 一覧の行（開いた直後 / 入力後） |',
  '| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
].join('\n');

/** 改善レポートに貼れる表の 1 行 */
export function formatRow(name: string, s: PageSummary): string {
  const typed = s.typedRuns[0] ?? { rows: Number.NaN, nodes: Number.NaN };
  const inp = (v: number, unreported: number) => `${ms(v)}${unreported > 0 ? `（${unreported}回は40ms未満）` : ''}`;
  return (
    `| ${name} | ${ms(s.lcp)} | ${inp(s.inputInp, s.inputUnreported)} | ${inp(s.clickInp, s.clickUnreported)} | ` +
    `${s.cls.toFixed(3)} | ${n(s.jsBytes)} バイト | ${n(s.opened.nodes)} / ${n(typed.nodes)} | ${n(s.opened.rows)} / ${n(typed.rows)} |`
  );
}

/** いまフォーカスがある要素を短い文字列にする。id があれば「#id」、それ以外は「ロール（なければタグ名）:テキスト」 */
export async function focused(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (el === null || el === document.body) return 'body';
    if (el.id) return `#${el.id}`;
    const role = el.getAttribute('role') ?? el.tagName.toLowerCase();
    return `${role}:${el.textContent?.trim() ?? ''}`;
  });
}

/** Tab を times 回押し、そのたびのフォーカス先を記録する */
export async function pressTab(page: Page, times: number): Promise<string[]> {
  const seen: string[] = [];
  for (let i = 0; i < times; i += 1) {
    await page.keyboard.press('Tab');
    seen.push(await focused(page));
  }
  return seen;
}

/** 条件を満たすまで待つ。待ちきれなければ何もしない（直後の check で NG として報告する） */
export async function tryWait(page: Page, fn: string): Promise<void> {
  try {
    await page.waitForFunction(fn, undefined, { timeout: 5_000 });
  } catch {
    // 下の check で NG として報告する
  }
}
