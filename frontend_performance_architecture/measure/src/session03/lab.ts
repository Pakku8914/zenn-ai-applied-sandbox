import { chromium, type Page } from 'playwright';
import { collectVitals, CONDITIONS, jsBytes, median, withPage } from '../vitals-client.ts';

/** どのスロットリングを掛けるか。両方 true のときは本書の標準条件（withPage）そのもの */
export type Throttle = { cpu: boolean; network: boolean };

export type LabRun = { lcp: number; requests: number; jsBytes: number };
export type LabResult = { lcp: number; lcps: number[]; requests: number; jsBytes: number };

/**
 * 条件の一部だけを外したページを開く。条件の効き目を分解する S03 専用の道具で、
 * 以降の章の計測は必ず withPage（標準条件）を使う。
 */
async function withLabPage<T>(throttle: Throttle, fn: (page: Page) => Promise<T>): Promise<T> {
  if (throttle.cpu && throttle.network) return withPage(fn);

  // --disable-features は渡さない（渡すと LCP が記録されなくなる）
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const context = await browser.newContext({ viewport: CONDITIONS.viewport });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    if (throttle.cpu) {
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: CONDITIONS.cpuThrottlingRate });
    }
    if (throttle.network) {
      await cdp.send('Network.enable');
      await cdp.send('Network.emulateNetworkConditions', {
        offline: false,
        latency: CONDITIONS.network.latencyMs,
        downloadThroughput: (CONDITIONS.network.downloadKbps * 1024) / 8,
        uploadThroughput: (CONDITIONS.network.uploadKbps * 1024) / 8,
      });
    }
    return await fn(page);
  } finally {
    await browser.close();
  }
}

/** 1回だけ開いて、LCP・リクエスト数・JS 量を返す */
export async function measureOnce(url: string, throttle: Throttle): Promise<LabRun> {
  return withLabPage(throttle, async (page) => {
    const vitals = await collectVitals(page, url);
    const lcp = vitals.find((v) => v.name === 'LCP');
    if (!lcp) throw new Error(`LCP が報告されませんでした: ${url}`);
    const requests = await page.evaluate(() => performance.getEntriesByType('resource').length);
    return { lcp: lcp.value, requests, jsBytes: await jsBytes(page) };
  });
}

/** 毎回新しいブラウザで runs 回計測し、中央値を返す */
export async function measureLab(url: string, throttle: Throttle, runs = 3): Promise<LabResult> {
  const results: LabRun[] = [];
  for (let i = 0; i < runs; i += 1) {
    results.push(await measureOnce(url, throttle));
  }
  const lcps = results.map((r) => r.lcp);
  return {
    lcp: median(lcps),
    lcps,
    requests: median(results.map((r) => r.requests)),
    jsBytes: median(results.map((r) => r.jsBytes)),
  };
}
