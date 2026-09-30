import { isRetryable } from '../retry';

export type Operation = {
  method: 'GET' | 'PUT' | 'DELETE' | 'POST';
  /** 同じキーの2回目以降をサーバーが「処理済み」として扱う仕組み（冪等キー）があるか */
  hasIdempotencyKey?: boolean;
};

/** 問題5：同じ操作を2回送っても結果が変わらないか */
export function isIdempotent(op: Operation): boolean {
  return op.method !== 'POST' || op.hasIdempotencyKey === true;
}

/** 失敗の種類（待てば直るか）と、操作の性質（2回送ってよいか）の両方が満たされたときだけリトライする */
export function shouldRetry(op: Operation, error: unknown): boolean {
  return isIdempotent(op) && isRetryable(error);
}
