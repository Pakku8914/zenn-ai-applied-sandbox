import type { Page } from 'playwright';
import { CONDITIONS } from '../vitals-client.ts';

/** S16 の検証で共有する定数と補助関数（verify*.ts ではないので verify-all.sh からは直接実行されない） */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
export const GOOD = `${TARGET}/pages/s16-catalog-good/`;
export const BAD = `${TARGET}/pages/s16-catalog-bad/`;

/** 読み込みが終わり、デバウンス後のライブリージョンに入る文 */
export const READY = '全 2,000 件を表示しています';

declare global {
  interface Window {
    __statusLog?: string[];
  }
}

/** Good 版はライブリージョンが READY になるまで、Bad 版は一覧の行が現れるまで待つ */
export async function waitReady(page: Page, kind: 'good' | 'bad'): Promise<void> {
  if (kind === 'good') {
    await page.waitForFunction((t) => document.querySelector('[role="status"]')?.textContent === t, READY, { timeout: 15_000 });
  } else {
    await page.waitForSelector('[data-viewport] li', { timeout: 15_000 });
  }
}

/**
 * いまフォーカスがある要素を、判定しやすい短い文字列にする。
 * id があれば「#id」、行（li）は「li:商品名」、それ以外は「ロール（なければタグ名）:テキスト」、どこにも無ければ「body」。
 */
export async function focused(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (el === null || el === document.body) return 'body';
    if (el.id) return `#${el.id}`;
    if (el.tagName === 'LI') return `li:${el.querySelector('span')?.textContent ?? ''}`;
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

/** 一覧の表示枠をスクロールする（マウスホイールでの移動に相当） */
export async function scrollViewport(page: Page, top: number): Promise<void> {
  await page.locator('[data-viewport]').evaluate((el, t) => {
    el.scrollTop = t;
  }, top);
}

export const scrollTopOf = (page: Page): Promise<number> => page.locator('[data-viewport]').evaluate((el) => el.scrollTop);

export const rowCount = (page: Page): Promise<number> => page.evaluate(() => document.querySelectorAll('[data-viewport] li').length);

/** 条件を満たすまで待つ。待ちきれなければ何もしない（直後の check で NG として報告する） */
export async function tryWait(page: Page, fn: string): Promise<void> {
  try {
    await page.waitForFunction(fn, undefined, { timeout: 5_000 });
  } catch {
    // 下の check で NG として報告する
  }
}

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
