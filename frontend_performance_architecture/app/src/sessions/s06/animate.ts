/**
 * S06：カートパネルを開くアニメーション。毎フレームの時刻を記録し、何フレーム描けたかを返す。
 * width 版は一覧の幅を縮めて横に並べる（毎フレーム 2,000 行のレイアウトとペイントが走る）。
 * transform 版はパネルを一覧の上に重ねて滑り込ませる（合成だけで済む）。
 * settle 版（練習問題7）は動いている間は transform だけを使い、一覧の幅は最後に1回だけ変える。
 */
export type AnimationKind = 'width' | 'transform' | 'settle';

export type FrameReport = {
  frames: number;
  averageIntervalMs: number;
  slowFrames: number;
};

const LIST_WIDTH_PX = 960;
const CART_WIDTH_PX = 320;
/** 60fps のフレーム予算 16.7ms の 1.5 倍を超えた間隔を「落ちたフレーム」とみなす */
const SLOW_FRAME_MS = (1000 / 60) * 1.5;

export function summarize(stamps: readonly number[]): FrameReport {
  const first = stamps[0] ?? 0;
  const last = stamps[stamps.length - 1] ?? first;
  let slowFrames = 0;
  for (let i = 1; i < stamps.length; i += 1) {
    if ((stamps[i] ?? 0) - (stamps[i - 1] ?? 0) > SLOW_FRAME_MS) slowFrames += 1;
  }
  const intervals = Math.max(stamps.length - 1, 1);
  return { frames: stamps.length, averageIntervalMs: (last - first) / intervals, slowFrames };
}

export function animateCart(
  kind: AnimationKind,
  list: HTMLElement,
  panel: HTMLElement,
  durationMs: number,
): Promise<FrameReport> {
  return new Promise((resolve) => {
    const stamps: number[] = [];
    let start: number | undefined;

    if (kind === 'width') {
      panel.style.transform = 'translateX(0)'; // パネルは最初から見せ、一覧の幅だけを動かす
    } else {
      panel.style.willChange = 'transform'; // 動かす直前にだけ宣言する
    }

    const step = (now: number): void => {
      start ??= now;
      const progress = Math.min((now - start) / durationMs, 1);
      if (kind === 'width') {
        // Bad：幅が変わるたびに 2,000 行のレイアウトとペイントをやり直す
        list.style.width = `${Math.round(LIST_WIDTH_PX - CART_WIDTH_PX * progress)}px`;
      } else {
        // Good：レイヤの位置を変えるだけ。レイアウトもペイントも起きない（transform 版・settle 版で共通）
        panel.style.transform = `translateX(${(1 - progress) * 100}%)`;
      }
      stamps.push(now);

      if (progress < 1) {
        requestAnimationFrame(step);
        return;
      }
      if (kind === 'settle') {
        // 並べた最終形のレイアウトは、動き終わった後に1回だけ計算させる
        list.style.width = `${LIST_WIDTH_PX - CART_WIDTH_PX}px`;
        void list.offsetHeight;
      }
      // 後片付け：次の実験に影響を残さない。will-change も動き終わったら外す
      list.style.width = '';
      panel.style.transform = '';
      panel.style.willChange = '';
      resolve(summarize(stamps));
    };

    requestAnimationFrame(step);
  });
}
