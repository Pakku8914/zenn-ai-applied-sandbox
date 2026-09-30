import type { Page } from 'playwright';

/**
 * セッション2「ブラウザは何をしているのか」で使う、performance エントリの読み出し。
 * ブラウザの中にあるエントリを、Node 側へ持ち出せる素の値だけの形にして返す。
 */
export type Snapshot = {
  navigation: {
    type: string;
    requestStart: number;
    responseStart: number;
    responseEnd: number;
    domInteractive: number;
    domContentLoadedEventStart: number;
    domContentLoadedEventEnd: number;
    domComplete: number;
    loadEventStart: number;
    loadEventEnd: number;
  }[];
  resources: {
    path: string;
    initiatorType: string;
    startTime: number;
    responseEnd: number;
    transferSize: number;
    decodedBodySize: number;
  }[];
  paints: { name: string; startTime: number }[];
};

export type Milestone = { 節目: string; 時刻ms: number; 前の節目からms: number };

export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

export async function readSnapshot(page: Page): Promise<Snapshot> {
  // この関数の中身はブラウザ側で実行される（Node 側の変数は参照できない）
  return page.evaluate(() => ({
    navigation: performance.getEntriesByType('navigation').map((entry) => {
      const n = entry as PerformanceNavigationTiming;
      return {
        type: n.type,
        requestStart: n.requestStart,
        responseStart: n.responseStart,
        responseEnd: n.responseEnd,
        domInteractive: n.domInteractive,
        domContentLoadedEventStart: n.domContentLoadedEventStart,
        domContentLoadedEventEnd: n.domContentLoadedEventEnd,
        domComplete: n.domComplete,
        loadEventStart: n.loadEventStart,
        loadEventEnd: n.loadEventEnd,
      };
    }),
    resources: performance.getEntriesByType('resource').map((entry) => {
      const r = entry as PerformanceResourceTiming;
      return {
        path: new URL(r.name).pathname,
        initiatorType: r.initiatorType,
        startTime: r.startTime,
        responseEnd: r.responseEnd,
        transferSize: r.transferSize,
        decodedBodySize: r.decodedBodySize,
      };
    }),
    paints: performance.getEntriesByType('paint').map((entry) => ({
      name: entry.name,
      startTime: entry.startTime,
    })),
  }));
}

/** 読み込んだ .js のうち、最後に取得を終えた時刻。JS が無ければ NaN。 */
export function lastJsEnd(snap: Snapshot): number {
  const js = snap.resources.filter((r) => r.path.endsWith('.js'));
  return js.length === 0 ? Number.NaN : Math.max(...js.map((r) => r.responseEnd));
}

/** ナビゲーション開始から FCP までの節目を時刻順に並べ、前の節目からの差を付ける。 */
export function buildMilestones(snap: Snapshot): Milestone[] {
  const nav = snap.navigation[0];
  if (!nav) throw new Error('navigation エントリがありません');
  const fcp = snap.paints.find((p) => p.name === 'first-contentful-paint');

  const points: [string, number][] = [
    ['ナビゲーション開始', 0],
    ['最初のバイト到着 responseStart', nav.responseStart],
    ['HTML 受信完了 responseEnd', nav.responseEnd],
    ['HTML パース完了 domInteractive', nav.domInteractive],
    ['JS 取得完了（最後の .js）', lastJsEnd(snap)],
    ['DOMContentLoaded 完了', nav.domContentLoadedEventEnd],
    ['load 完了 loadEventEnd', nav.loadEventEnd],
    ['FCP first-contentful-paint', fcp?.startTime ?? Number.NaN],
  ];
  const sorted = points.filter(([, t]) => Number.isFinite(t)).sort((a, b) => a[1] - b[1]);

  return sorted.map(([label, t], i) => ({
    節目: label,
    時刻ms: round1(t),
    前の節目からms: i === 0 ? 0 : round1(t - sorted[i - 1]![1]),
  }));
}
