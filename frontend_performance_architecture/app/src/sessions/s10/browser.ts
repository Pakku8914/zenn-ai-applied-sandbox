import type { ApiCall } from './fakeApi';

declare global {
  interface Window {
    /** 検証スクリプトが擬似 API の呼び出し記録を読むための入口 */
    __s10Calls?: ApiCall[];
    /** 画面に必要なデータがすべて表示された時刻（performance.now()） */
    __s10DoneAt?: number;
  }
}

export function exposeCalls(calls: ApiCall[]): void {
  window.__s10Calls = calls;
}

export function markDone(): void {
  window.__s10DoneAt ??= performance.now();
}
