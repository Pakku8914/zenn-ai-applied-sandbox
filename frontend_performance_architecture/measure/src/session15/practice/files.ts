import type { Page } from 'playwright';

export type FileSize = { file: string; bytes: number };
export type FileDiff = { name: string; previous: number; current: number; delta: number };

/** ビルドのたびに変わるハッシュ（- の後ろの 8 文字）を取り除き、同じファイルとして比べられる名前にする */
export function normalizeName(file: string): string {
  return file.replace(/-[\w-]{8}\.js$/, '.js');
}

function sumByName(files: readonly FileSize[]): Map<string, number> {
  const totals = new Map<string, number>();
  for (const { file, bytes } of files) {
    const name = normalizeName(file);
    totals.set(name, (totals.get(name) ?? 0) + bytes);
  }
  return totals;
}

/**
 * 問題8：前回と今回の JS ファイルごとのサイズを比べ、増減の大きい順に返す。
 * 追加されたファイルは previous 0、消えたファイルは current 0。増減が 0 のファイルは含めない。
 */
export function diffFiles(previous: readonly FileSize[], current: readonly FileSize[]): FileDiff[] {
  const before = sumByName(previous);
  const after = sumByName(current);
  const names = new Set([...before.keys(), ...after.keys()]);
  return [...names]
    .map((name) => {
      const p = before.get(name) ?? 0;
      const c = after.get(name) ?? 0;
      return { name, previous: p, current: c, delta: c - p };
    })
    .filter((d) => d.delta !== 0)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.name.localeCompare(b.name));
}

/** ページが読み込んだ JS をファイルごとに返す（合計は vitals-client の jsBytes と同じ） */
export async function jsFiles(page: Page): Promise<FileSize[]> {
  return page.evaluate(() =>
    performance
      .getEntriesByType('resource')
      .filter((e) => new URL(e.name).pathname.endsWith('.js'))
      .map((e) => ({ file: new URL(e.name).pathname, bytes: (e as PerformanceResourceTiming).decodedBodySize })),
  );
}
