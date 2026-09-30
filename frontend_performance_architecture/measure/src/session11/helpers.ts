import type { Page } from 'playwright';
import { CONDITIONS } from '../vitals-client.ts';

/** S11 の検証で共有する定数と補助関数（verify*.ts ではないので verify-all.sh からは直接実行されない） */
export const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
export const KEYWORD = '商品1';

/** 「商品1」を含む件数。2,000 件なら 1,111 件、20,000 件なら 11,111 件 */
export function matchedFor(total: number): number {
  if (total === 2_000) return 1_111;
  if (total === 20_000) return 11_111;
  throw new Error(`想定していない件数です: ${total}`);
}

/** 見出し「商品一覧（N 件）」が期待の件数になるまで待つ（全件描画版は再レンダリングが追いつくまで時間がかかる） */
export async function waitForCount(page: Page, count: number): Promise<void> {
  await page.waitForFunction(
    (c) => document.querySelector('section h2')?.textContent?.includes(`（${c} 件）`) ?? false,
    count,
    { timeout: 15_000 },
  );
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
