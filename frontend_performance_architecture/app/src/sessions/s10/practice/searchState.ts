import type { Product } from '../../../data/products';
import { assertNever } from '../requestState';

/**
 * 問題2：検索結果の状態。「前の結果を出したまま取り直している」も1つの状態として名前を付ける。
 * refreshing だけが data を持ったまま通信中になれる。loading は data を持てない。
 */
export type SearchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'refreshing'; data: readonly Product[] }
  | { status: 'success'; data: readonly Product[] }
  | { status: 'error'; error: Error; data?: readonly Product[] };

/** 旧来の3つのフラグから変換する。矛盾した組み合わせはここで1つに決める */
export function fromFlags(flags: {
  isLoading: boolean;
  error: Error | null;
  data: readonly Product[] | null;
}): SearchState {
  if (flags.error !== null) {
    return flags.data === null ? { status: 'error', error: flags.error } : { status: 'error', error: flags.error, data: flags.data };
  }
  if (flags.isLoading) return flags.data === null ? { status: 'loading' } : { status: 'refreshing', data: flags.data };
  return flags.data === null ? { status: 'idle' } : { status: 'success', data: flags.data };
}

export function statusText(state: SearchState): string {
  switch (state.status) {
    case 'idle':
      return 'キーワードを入力してください';
    case 'loading':
      return '読み込み中…';
    case 'refreshing':
      return `${state.data.length} 件（更新を確認中）`;
    case 'success':
      return `${state.data.length} 件`;
    case 'error':
      return state.data === undefined
        ? `読み込めませんでした（${state.error.message}）`
        : `${state.data.length} 件（最新の取得に失敗しました）`;
    default:
      return assertNever(state);
  }
}
