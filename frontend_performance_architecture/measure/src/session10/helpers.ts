import type { Page } from 'playwright';

/**
 * S10 の検証で共通に使う小道具。ファイル名が verify* ではないので verify-all.sh からは直接実行されない。
 */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';

export function pageUrl(name: string): string {
  return `${TARGET}/pages/${name}/`;
}

/** ページ側の擬似 API が記録した呼び出し（app/src/sessions/s10/fakeApi.ts の ApiCall と同じ形） */
export type ApiCall = { op: string; key: string; startedAt: number; endedAt?: number; outcome?: string };

export async function readCalls(page: Page): Promise<ApiCall[]> {
  return page.evaluate(() => [...((window as unknown as { __s10Calls?: ApiCall[] }).__s10Calls ?? [])]);
}

/** 同時に走っていた呼び出しの最大数 */
export function maxConcurrency(calls: readonly ApiCall[]): number {
  const events = calls.flatMap((c) => [
    { t: c.startedAt, d: 1 },
    { t: c.endedAt ?? Infinity, d: -1 },
  ]);
  // 同じ時刻なら終了を先に数える（終わった直後に始まったものを「同時」としない）
  events.sort((a, b) => a.t - b.t || a.d - b.d);
  let current = 0;
  let max = 0;
  for (const e of events) {
    current += e.d;
    max = Math.max(max, current);
  }
  return max;
}

/** 見出し「商品一覧（N 件）」の N と、「『…』の検索結果」のキーワードを読む */
export async function readResult(page: Page): Promise<{ count: number | null; keyword: string | null }> {
  return page.evaluate(() => {
    const count = document.querySelector('section h2')?.textContent?.match(/（(\d+) 件）/)?.[1];
    const keyword = document.querySelector('#result-keyword')?.textContent?.match(/「(.*)」/)?.[1];
    return { count: count === undefined ? null : Number(count), keyword: keyword ?? null };
  });
}

/** すべての呼び出しが終わる（応答・失敗・中断のいずれか）まで待つ */
export async function waitForSettled(page: Page, expectedCalls: number): Promise<void> {
  await page.waitForFunction(
    (n) => {
      const calls = (window as unknown as { __s10Calls?: { endedAt?: number }[] }).__s10Calls ?? [];
      return calls.length >= n && calls.every((c) => c.endedAt !== undefined);
    },
    expectedCalls,
    { timeout: 15_000 },
  );
  await page.waitForTimeout(200); // 最後の応答による再レンダリングを待つ
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
