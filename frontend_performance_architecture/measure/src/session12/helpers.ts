import type { Page } from 'playwright';

/**
 * S12 の検証で共通に使う小道具。ファイル名が verify* ではないので verify-all.sh からは直接実行されない。
 */
export const NEXT = process.env.NEXT_URL ?? 'http://next.test:3000';
export const SPA = `${process.env.TARGET_URL ?? 'http://preview.test:4173'}/pages/s12-spa/`;

export function nextUrl(path: string): string {
  return `${NEXT}/${path}`;
}

export function createChecker() {
  const failures: string[] = [];
  return {
    check(name: string, ok: boolean, detail = ''): void {
      console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
      if (!ok) failures.push(name);
    },
    finish(label: string): void {
      if (failures.length > 0) {
        console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
        process.exit(1);
      }
      console.log(`\n${label}の検証に成功しました。`);
    },
  };
}

/** 一覧の見出し（「商品一覧（N 件）」）と行数 */
export async function readList(page: Page): Promise<{ heading: string | null; rows: number }> {
  return page.evaluate(() => ({
    heading: document.querySelector('section h2')?.textContent ?? null,
    rows: document.querySelectorAll('section ul li').length,
  }));
}

export async function waitForHeading(page: Page, text: string): Promise<void> {
  await page.waitForFunction((t) => document.querySelector('section h2')?.textContent === t, text, {
    timeout: 15_000,
  });
}

/** ハイドレーション（SPA は初回マウント）が終わるまで待ち、FCP と並べて返す */
export async function readHydration(page: Page): Promise<{ fcp: number; hydratedAt: number }> {
  // SPA は初回マウント直後の useEffect が最初の描画より先に走ることがあるので、
  // FCP のエントリが記録されるまで待ってから読む
  await page.waitForFunction(
    () =>
      (window as unknown as { __s12HydratedAt?: number }).__s12HydratedAt !== undefined &&
      performance.getEntriesByName('first-contentful-paint').length > 0,
    undefined,
    { timeout: 15_000 },
  );
  return page.evaluate(() => ({
    fcp: performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? -1,
    hydratedAt: (window as unknown as { __s12HydratedAt: number }).__s12HydratedAt,
  }));
}

/** ページが読み込んだ .js をすべて取り直して、中身を1つの文字列にする（目印の文字列を探すため） */
export async function loadedScriptText(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const urls = performance
      .getEntriesByType('resource')
      .map((e) => e.name)
      .filter((name) => new URL(name).pathname.endsWith('.js'));
    const texts = await Promise.all(urls.map((u) => fetch(u).then((r) => r.text())));
    return texts.join('\n');
  });
}

/**
 * HTML をストリームのまま読み、最初のチャンクが届いた時刻と、各目印の文字列が現れた時刻を記録する。
 * 圧縮するとまとめて送られることがあるので、この確認では圧縮なし（identity）を要求する。
 */
export async function streamTimeline(
  url: string,
  markers: Record<string, string>,
): Promise<{ firstChunkMs: number; at: Record<string, number | null>; html: string }> {
  const started = performance.now();
  const res = await fetch(url, { headers: { 'accept-encoding': 'identity' } });
  if (!res.body) throw new Error(`${url}: 本文がありません`);
  const decoder = new TextDecoder();
  const at: Record<string, number | null> = Object.fromEntries(Object.keys(markers).map((k) => [k, null]));
  let html = '';
  let firstChunkMs = -1;
  for await (const chunk of res.body) {
    const now = Math.round(performance.now() - started);
    if (firstChunkMs < 0) firstChunkMs = now;
    html += decoder.decode(chunk, { stream: true });
    for (const [key, marker] of Object.entries(markers)) {
      if (at[key] === null && html.includes(marker)) at[key] = now;
    }
  }
  return { firstChunkMs, at, html };
}
