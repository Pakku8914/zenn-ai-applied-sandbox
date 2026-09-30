import type { Page } from 'playwright';

/**
 * S09 の検証で共通に使う小道具。ファイル名が verify* ではないので verify-all.sh からは直接実行されない。
 */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';

export function pageUrl(name: string, search = ''): string {
  return `${TARGET}/pages/${name}/${search}`;
}

export type Renders = Record<string, number>;

/** ページ側の手動カウンタ（window.__s09RenderCount）を読む */
export async function readRenders(page: Page): Promise<Renders> {
  return page.evaluate(() => ({
    ...((window as unknown as { __s09RenderCount?: Record<string, number> }).__s09RenderCount ?? {}),
  }));
}

export function diffRenders(before: Renders, after: Renders, names: readonly string[]): Renders {
  return Object.fromEntries(names.map((n) => [n, (after[n] ?? 0) - (before[n] ?? 0)]));
}

/** 見出し「商品一覧（N 件）」の N を読む */
export async function readCount(page: Page): Promise<number | null> {
  const text = await page.locator('section h2').textContent();
  const match = text?.match(/（(\d+) 件）/);
  return match ? Number(match[1]) : null;
}

/** 件数が expected になるまで待つ（ならなければ、そのときの件数を返して呼び出し側で NG にする） */
export async function waitForCount(page: Page, expected: number): Promise<number | null> {
  await page
    .waitForFunction(
      (n) => document.querySelector('section h2')?.textContent?.includes(`（${n} 件）`) ?? false,
      expected,
      { timeout: 10_000 },
    )
    .catch(() => undefined);
  return readCount(page);
}

/** index 番目の行の「カートに入れる」を押し、カートの点数が expectedTotal になるまで待つ */
export async function clickAdd(page: Page, index: number, expectedTotal: number): Promise<void> {
  await page.locator('section li').nth(index).getByRole('button', { name: 'カートに入れる' }).click();
  await page.waitForFunction(
    (n) => document.querySelector('#cart-count')?.textContent?.includes(`${n} 点`) ?? false,
    expectedTotal,
    { timeout: 10_000 },
  );
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

/** 操作ごとの増分を「コンポーネント × 操作」の表で出す */
export function printTable(title: string, names: readonly string[], columns: Record<string, Renders>): void {
  const labels = Object.keys(columns);
  console.log(`\n[${title}]`);
  console.log(`${'コンポーネント'.padEnd(16)}${labels.map((l) => l.padStart(14)).join('')}`);
  for (const name of names) {
    console.log(`${name.padEnd(16)}${labels.map((l) => String(columns[l]?.[name] ?? 0).padStart(14)).join('')}`);
  }
}
