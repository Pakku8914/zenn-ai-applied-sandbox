// 速さを数字にする道具（セッション27）。
//
// 「なんとなく重い」では直せない。どこに何ミリ秒かかったのかを数字にして、
// 直したあとにもう一度測って比べる。ここには測るための小さな関数だけを置く。
// 同じ実装を src/session27/verify.ts で検証している。

/** 小数第1位までに丸める。ログに 12.345678 のような値を並べても読めないため */
export function roundMs(value: number): number {
  return Math.round(value * 10) / 10;
}

/** 測定結果1件 */
export type TimingEntry = {
  name: string;
  durationMs: number;
};

/**
 * 非同期処理の所要時間を測る。処理そのものには手を入れない。
 * performance.now() は「起動からの経過ミリ秒」なので、時計の変更に影響されない。
 */
export async function measure<T>(
  name: string,
  task: () => Promise<T>
): Promise<TimingEntry & { value: T }> {
  const startedAt = performance.now();
  const value = await task();

  return { name, durationMs: roundMs(performance.now() - startedAt), value };
}

/**
 * ブラウザの開発者ツールに「サーバー内訳」として表示させるヘッダの値を作る。
 * 例: db;dur=12.3, render;dur=4.5
 * ルートハンドラなどレスポンスを自分で組み立てる場所で Server-Timing ヘッダに載せる。
 */
export function formatServerTiming(entries: readonly TimingEntry[]): string {
  return entries.map((entry) => `${entry.name};dur=${roundMs(entry.durationMs)}`).join(', ');
}

// ---------------------------------------------------------------------------
// 転送量の見積り
// ---------------------------------------------------------------------------

/**
 * 一覧の転送量をざっくり見積もる（バイト）。
 * 1件あたりのバイト数は環境で変わるので定数にせず、必ず引数で受け取る。
 */
export function estimateTransferBytes(
  itemCount: number,
  bytesPerItem: number,
  overheadBytes: number
): number {
  return itemCount * bytesPerItem + overheadBytes;
}

/** 改善前と改善後から削減率（%・整数）を求める。改善前が0なら0% */
export function savedRatioPercent(beforeBytes: number, afterBytes: number): number {
  if (beforeBytes <= 0) {
    return 0;
  }

  return Math.round((1 - afterBytes / beforeBytes) * 100);
}

// ---------------------------------------------------------------------------
// Core Web Vitals の判定
// ---------------------------------------------------------------------------

/** 本書で扱う3つの指標。LCP と INP はミリ秒、CLS は単位なし */
export type WebVitalName = 'LCP' | 'INP' | 'CLS';

/** 判定結果。good（良好）/ needs-improvement（改善が必要）/ poor（不良） */
export type WebVitalRating = 'good' | 'needs-improvement' | 'poor';

/**
 * しきい値（2026-08 時点の Google の基準）。
 * good 以下なら good、poor 以下なら needs-improvement、それより大きければ poor。
 */
export const WEB_VITAL_THRESHOLDS: Record<WebVitalName, { good: number; poor: number }> = {
  LCP: { good: 2500, poor: 4000 },
  INP: { good: 200, poor: 500 },
  CLS: { good: 0.1, poor: 0.25 },
};

export function rateWebVital(name: WebVitalName, value: number): WebVitalRating {
  const threshold = WEB_VITAL_THRESHOLDS[name];

  if (value <= threshold.good) {
    return 'good';
  }
  if (value <= threshold.poor) {
    return 'needs-improvement';
  }

  return 'poor';
}

/** 3つの指標のうち1つでも poor があれば poor、needs-improvement があればそれ、なければ good */
export function rateOverall(ratings: readonly WebVitalRating[]): WebVitalRating {
  if (ratings.includes('poor')) {
    return 'poor';
  }
  if (ratings.includes('needs-improvement')) {
    return 'needs-improvement';
  }

  return 'good';
}
