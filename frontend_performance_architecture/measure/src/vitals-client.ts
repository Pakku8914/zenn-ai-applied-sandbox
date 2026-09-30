import { chromium, type Browser, type Page } from 'playwright';

export type Vital = { name: string; value: number; rating: string };

/**
 * 計測条件を固定する。本書に載せる数値はすべてこの条件で取ったものに揃える。
 * CPU とネットワークを絞るのは、開発機の性能差で結論が変わらないようにするため。
 */
export const CONDITIONS = {
  cpuThrottlingRate: 4,
  network: { downloadKbps: 1_500, uploadKbps: 750, latencyMs: 40 },
  viewport: { width: 1280, height: 800 },
} as const;

export async function withPage<T>(fn: (page: Page) => Promise<T>): Promise<T> {
  const browser: Browser = await chromium.launch({
    // --disable-features は絶対に自分で指定しないこと。
    // Playwright は既定で PaintHolding などを無効化しており、ここで上書きすると
    // その既定が消えて LCP のエントリが記録されなくなる（原因が分かりにくい）。
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const context = await browser.newContext({ viewport: CONDITIONS.viewport });
    const page = await context.newPage();

    // Chrome DevTools Protocol で CPU とネットワークを絞る
    const cdp = await context.newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: CONDITIONS.cpuThrottlingRate });
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: CONDITIONS.network.latencyMs,
      downloadThroughput: (CONDITIONS.network.downloadKbps * 1024) / 8,
      uploadThroughput: (CONDITIONS.network.uploadKbps * 1024) / 8,
    });

    return await fn(page);
  } finally {
    await browser.close();
  }
}

/** ページを開いて Core Web Vitals が報告されるまで待ち、収集した値を返す。 */
export async function collectVitals(page: Page, url: string): Promise<Vital[]> {
  await page.goto(url, { waitUntil: 'load' });

  // ここで先にクリックなどの入力をしてはいけない。
  // web-vitals は最初の入力を「LCP の観測を打ち切る合図」として扱い、その時点で
  // まだ LCP エントリが届いていないと observer を切ってしまう。すると値は永久に取れない。
  // reportAllChanges を有効にしてあるので、入力なしでも LCP は報告される。
  await page.waitForFunction(
    () => (window.__webVitals ?? []).some((m) => m.name === 'LCP'),
    undefined,
    { timeout: 15_000 },
  );

  const raw = await page.evaluate(() => window.__webVitals ?? []);
  return latestPerName(raw);
}

/**
 * INP を計測するための入力を行い、更新後の値を返す。
 * 必ず collectVitals（LCP の取得）を終えたあとに呼ぶこと。
 */
export async function interactAndCollect(page: Page, selector: string, value: string): Promise<Vital[]> {
  // page.fill() は値を直接設定するだけで keydown が発生しないため INP が計測されない。
  // 実際のキー入力を再現する pressSequentially を使う。
  await page.click(selector);
  await page.locator(selector).pressSequentially(value, { delay: 60 });
  await page.waitForTimeout(800);
  const raw = await page.evaluate(() => window.__webVitals ?? []);
  return latestPerName(raw);
}

/** 同じ指標が複数回報告されるため、指標ごとに最後の値（確定値）だけを残す。 */
export function latestPerName(metrics: Vital[]): Vital[] {
  const byName = new Map<string, Vital>();
  for (const m of metrics) {
    byName.set(m.name, m);
  }
  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
}

declare global {
  interface Window {
    __webVitals?: Vital[];
  }
}

/** 中央値。CLS のように実行ごとに揺れる指標は、1回の値ではなく中央値で比べる。 */
export function median(values: readonly number[]): number {
  if (values.length === 0) throw new Error('median: 値が1つもありません');
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

/** ページが読み込んだ JS の合計バイト数（展開後）。分割の効果を「初期 JS 量」で比べるために使う。 */
export async function jsBytes(page: Page): Promise<number> {
  return page.evaluate(() =>
    performance
      .getEntriesByType('resource')
      .filter((e) => new URL(e.name).pathname.endsWith('.js'))
      .reduce((sum, e) => sum + (e as PerformanceResourceTiming).decodedBodySize, 0),
  );
}

export type RunResult = { vitals: Vital[]; jsBytes: number };

/**
 * 同じ URL を runs 回（毎回新しいブラウザで）計測し、指標ごとの中央値を返す。
 * input を渡すと LCP 取得後にその入力を行い、INP も計測する。
 */
export async function measureMedian(
  url: string,
  options: { runs?: number; input?: { selector: string; value: string } } = {},
): Promise<{ median: Record<string, number>; runs: RunResult[] }> {
  const runs: RunResult[] = [];
  for (let i = 0; i < (options.runs ?? 3); i += 1) {
    runs.push(
      await withPage(async (page) => {
        let vitals = await collectVitals(page, url);
        if (options.input) {
          vitals = await interactAndCollect(page, options.input.selector, options.input.value);
        }
        return { vitals, jsBytes: await jsBytes(page) };
      }),
    );
  }
  const names = new Set(runs.flatMap((r) => r.vitals.map((v) => v.name)));
  const result: Record<string, number> = { jsBytes: median(runs.map((r) => r.jsBytes)) };
  for (const name of names) {
    result[name] = median(runs.flatMap((r) => r.vitals.filter((v) => v.name === name).map((v) => v.value)));
  }
  return { median: result, runs };
}
