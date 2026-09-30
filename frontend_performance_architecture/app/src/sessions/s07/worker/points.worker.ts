import { buildPointsSync } from '../points';
import type { PointsRequest, PointsResponse } from './protocol';

// tsconfig は画面用の型（DOM）だけを読むため、self は Window として型付けされてしまう。
// Worker の中で使う機能だけを、ここで型として宣言しておく。
type WorkerScope = {
  addEventListener(type: 'message', listener: (event: MessageEvent<PointsRequest>) => void): void;
  postMessage(message: PointsResponse): void;
};
const scope = self as unknown as WorkerScope;

scope.addEventListener('message', (event) => {
  if (event.data.kind !== 'build') return;
  // ここは Worker のスレッドなので、同期のまま計算してもメインスレッドは塞がらない
  scope.postMessage({ kind: 'done', points: buildPointsSync() });
});
