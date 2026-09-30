/**
 * 横断復習② 問題8：「入力すると固まる」原因を、計測した証拠から1つに絞る純粋な関数。
 * ブラウザにも DOM にも触らない。入力は数値だけなので、証拠の取り方（evidence.ts）と切り離して検査できる。
 */
export type Evidence = {
  /** 入力の回数（「商品1」なら 3） */
  inputs: number;
  /** web-vitals が報告した INP。40ms 未満の操作は報告されないので null */
  inpMs: number | null;
  /** 入力している間に行コンポーネントの本体が実行された回数（S08 の手動カウンタ） */
  rowRenders: number;
  /** 入力している間のレイアウトの実行回数（CDP の LayoutCount の差。S06） */
  layouts: number;
};

export type Cause = 'layout' | 'rerender' | 'long-task';

export type Verdict = {
  cause: Cause;
  /** INP が good の範囲を外れているか。外れていなければ、原因が見えても今は直さない */
  worthFixing: boolean;
};

/** INP の good の上限（これ以上は needs-improvement）。S03 の表の値 */
export const INP_GOOD_MS = 200;
/** 1回の入力でレイアウトがこれだけ起きたら、読み書きの交互（強制同期レイアウト）を疑う */
export const LAYOUTS_PER_INPUT = 100;
/** 1回の入力で行がこれだけ実行されたら、再レンダリングの範囲が広すぎると見る */
export const ROW_RENDERS_PER_INPUT = 1_000;

export const CAUSE_LABEL: Record<Cause, string> = {
  layout: '描画（強制同期レイアウト）',
  rerender: '再レンダリングの範囲',
  'long-task': '長いタスク（重い計算）',
};

export function diagnose(e: Evidence): Verdict {
  if (!Number.isInteger(e.inputs) || e.inputs < 1) {
    throw new Error(`inputs は 1 以上の整数にしてください（${e.inputs}）`);
  }
  // 強制同期レイアウトの時間は JS の実行時間の中に数えられるので、先に確かめて除外する
  const cause: Cause =
    e.layouts / e.inputs >= LAYOUTS_PER_INPUT
      ? 'layout'
      : e.rowRenders / e.inputs >= ROW_RENDERS_PER_INPUT
        ? 'rerender'
        : 'long-task';
  return { cause, worthFixing: e.inpMs !== null && e.inpMs >= INP_GOOD_MS };
}
