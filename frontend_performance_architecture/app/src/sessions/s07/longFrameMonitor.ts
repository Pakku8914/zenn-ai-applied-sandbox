/**
 * 長いタスク（50ms 以上メインスレッドを占有した処理）を PerformanceObserver で記録する。
 * long-animation-frame（LoAF）が使えればそれを、無ければ longtask を使う。
 */
export type LongFrameType = 'long-animation-frame' | 'longtask';

export type LongFrame = {
  type: LongFrameType;
  startTime: number;
  duration: number;
  /** LoAF だけが持つ「入力を待たせた時間」。longtask では null */
  blockingDuration: number | null;
  /** LoAF だけが持つ、そのフレームで長く動いたスクリプトの呼び出し元（例: BUTTON.onclick） */
  invokers: string[];
};

type LoafEntry = PerformanceEntry & {
  blockingDuration?: number;
  scripts?: ReadonlyArray<{ invoker?: string }>;
};

declare global {
  interface Window {
    __longFrames?: LongFrame[];
  }
}

export function detectLongFrameType(): LongFrameType | null {
  const supported = PerformanceObserver.supportedEntryTypes;
  if (supported.includes('long-animation-frame')) return 'long-animation-frame';
  if (supported.includes('longtask')) return 'longtask';
  return null;
}

/** 長いフレームを見つけるたびに onFrame を呼ぶ。戻り値は監視をやめる関数。 */
export function observeLongFrames(onFrame: (frame: LongFrame) => void): () => void {
  const type = detectLongFrameType();
  if (type === null) return () => undefined;

  const observer = new PerformanceObserver((list) => {
    for (const entry of list.getEntries() as LoafEntry[]) {
      onFrame({
        type,
        startTime: entry.startTime,
        duration: entry.duration,
        blockingDuration: entry.blockingDuration ?? null,
        invokers: (entry.scripts ?? []).map((s) => s.invoker ?? '(不明)'),
      });
    }
  });
  // buffered: true で、監視を始める前に起きた分もさかのぼって受け取る
  observer.observe({ type, buffered: true });
  return () => observer.disconnect();
}

/** 計測用：記録を window.__longFrames に貯める（Playwright から読む）。 */
export function startLongFrameMonitor(): void {
  window.__longFrames = [];
  observeLongFrames((frame) => {
    window.__longFrames?.push(frame);
  });
}
