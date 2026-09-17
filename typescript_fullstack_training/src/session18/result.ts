// セッション18で使う Result 型と、例外と Result を行き来させる道具。
//
// 型そのものは「セッション13：ジェネリクス」で定義したものと同じ。
// この章では「どこで使うか」を設計するために、境界の変換関数を足している。

import { toError } from './errors';

/** 成功なら value、失敗なら error。セッション13で定義したものと同じ型 */
export type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

/** 成功の Result を作る */
export function ok<T>(value: T): Result<T, never> {
  return { kind: 'ok', value };
}

/** 失敗の Result を作る */
export function err<E>(error: E): Result<never, E> {
  return { kind: 'error', error };
}

/** 全部成功なら値の配列、1つでも失敗なら失敗だけを集めた配列を返す */
export function collectResults<T, E>(results: readonly Result<T, E>[]): Result<T[], E[]> {
  const values: T[] = [];
  const errors: E[] = [];

  for (const result of results) {
    if (result.kind === 'ok') {
      values.push(result.value);
    } else {
      errors.push(result.error);
    }
  }
  return errors.length === 0 ? ok(values) : err(errors);
}

// --- 境界の変換（例外 <-> Result）-----------------------------------------

/** 例外を投げる同期処理を Result に変える（境界の内向き変換） */
export function tryCatch<T>(fn: () => T): Result<T, Error> {
  try {
    return ok(fn());
  } catch (caught: unknown) {
    return err(toError(caught));
  }
}

/** 例外を投げる非同期処理を Result に変える（await の失敗も拾う） */
export async function tryCatchAsync<T>(fn: () => Promise<T>): Promise<Result<T, Error>> {
  try {
    return ok(await fn());
  } catch (caught: unknown) {
    return err(toError(caught));
  }
}

/** Result を例外に変える（境界の外向き変換）。使うのは「起きないはず」の場所だけ */
export function unwrapOrThrow<T, E>(result: Result<T, E>, toThrown: (error: E) => Error): T {
  if (result.kind === 'error') {
    throw toThrown(result.error);
  }
  return result.value;
}
