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
