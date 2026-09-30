/**
 * 1回の取得の状態。status で分岐させ、「読み込み中なのにデータもある」のような
 * 矛盾した組み合わせを型のうえで作れないようにする（判別可能ユニオン）。
 */
export type RequestState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: Error };

export function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

/** 取りこぼしを型で検出する。case を足し忘れると、ここで型エラーになる */
export function assertNever(value: never): never {
  throw new Error(`想定していない状態です: ${JSON.stringify(value)}`);
}

/** 状態から画面の文言を決める。switch が全ケースを網羅していないとコンパイルが通らない */
export function describeState<T>(state: RequestState<T>, count: (data: T) => number): string {
  switch (state.status) {
    case 'idle':
      return 'キーワードを入力してください';
    case 'loading':
      return '読み込み中…';
    case 'success':
      return `${count(state.data)} 件`;
    case 'error':
      return `読み込めませんでした（${state.error.message}）`;
    default:
      return assertNever(state);
  }
}
