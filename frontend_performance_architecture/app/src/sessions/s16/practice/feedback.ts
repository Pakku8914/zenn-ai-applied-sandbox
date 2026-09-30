import { LOADING_MESSAGE, loadErrorMessage, resultMessage, saveErrorMessage } from '../a11yModel';

/** 問題5：画面の状態ごとに「どのロールで・何を・次に何をするか」を 1 か所で決める */
export type CatalogState =
  | { kind: 'loading' }
  | { kind: 'ready'; count: number; total: number; filtered: boolean }
  | { kind: 'load-failed'; status: number }
  | { kind: 'save-failed'; productName: string };

export type Feedback = {
  /** status は割り込まずに読む、alert は割り込んで読む */
  role: 'status' | 'alert';
  text: string;
  /** 一覧の領域に付ける aria-busy */
  busy: boolean;
  /** 次の操作として出すボタンのラベル。不要なら null */
  action: string | null;
};

export function feedbackFor(state: CatalogState): Feedback {
  switch (state.kind) {
    case 'loading':
      return { role: 'status', text: LOADING_MESSAGE, busy: true, action: null };
    case 'ready':
      return {
        role: 'status',
        text: resultMessage(state.count, state.total, state.filtered),
        busy: false,
        action: state.filtered && state.count === 0 ? '条件をクリア' : null,
      };
    case 'load-failed':
      return { role: 'alert', text: loadErrorMessage(state.status), busy: false, action: 'もう一度読み込む' };
    case 'save-failed':
      // もう一度押せばよいので、別のボタンは出さない（押したボタンがそのまま次の操作になる）
      return { role: 'alert', text: saveErrorMessage(state.productName), busy: false, action: null };
    default: {
      const unreachable: never = state;
      throw new Error(`想定していない状態です: ${JSON.stringify(unreachable)}`);
    }
  }
}
