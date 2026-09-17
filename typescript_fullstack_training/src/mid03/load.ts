// ファイルを「読む」ことだけを担当するモジュール。
// 制限時間・再試行・失敗の分類までがここの責任で、
// 中身が正しいかどうか（検証）は validate.ts の仕事。

import { readFile } from 'node:fs/promises';
import { isAbortLike, retryWithBackoff, withTimeout } from '../session17/async-tools';
import { fixturePath } from '../session17/fixtures-path';
import { InvariantError, toMessage } from '../session18/errors';
import { collectResults, err, ok } from '../session18/result';
import type { Result } from '../session18/result';
import type { LoadError } from './types';

/** テキストを1つ読む係。テストで差し替えられるように型に名前を付けておく */
export type JsonReader = (fileName: string, signal: AbortSignal) => Promise<string>;

/** 既定の読み込み係。fixtures フォルダから読む（ネットワークは使わない） */
export const readFixtureText: JsonReader = async (fileName, signal) =>
  readFile(fixturePath(fileName), { encoding: 'utf-8', signal });

export type LoadOptions = {
  /** 1回の試行に許す時間（ミリ秒） */
  timeoutMs: number;
  /** 追加で試す回数（合計の試行回数は retries + 1 回） */
  retries: number;
  /** 1回目の待ち時間（ミリ秒）。2回目以降は2倍ずつ増える */
  baseMs: number;
};

export const DEFAULT_LOAD_OPTIONS: LoadOptions = { timeoutMs: 1000, retries: 2, baseMs: 20 };

/** 再試行したことを外に伝える通知。画面に出すかどうかは main.ts が決める */
export type RetryNotice = (fileName: string, attempt: number, waitMs: number) => void;

/** 1ファイルを読む。制限時間を超えたら中断し、失敗は Result で返す */
export async function loadText(
  fileName: string,
  options: LoadOptions,
  read: JsonReader = readFixtureText,
  onRetry?: RetryNotice
): Promise<Result<string, LoadError>> {
  try {
    const text = await retryWithBackoff(
      () => withTimeout((signal) => read(fileName, signal), options.timeoutMs),
      { retries: options.retries, baseMs: options.baseMs },
      (attempt, waitMs) => onRetry?.(fileName, attempt, waitMs)
    );
    return ok(text);
  } catch (caught: unknown) {
    // catch に来る値は unknown。ここで「このプロジェクトの失敗の言葉」に翻訳する
    if (isAbortLike(caught)) {
      return err<LoadError>({ kind: 'timeout', fileName, limitMs: options.timeoutMs });
    }
    return err<LoadError>({ kind: 'read_failed', fileName, detail: toMessage(caught) });
  }
}

/** 読み込んだ2つのテキスト。どちらがどのファイルかを名前で区別する */
export type LoadedSources = { productsText: string; categoriesText: string };

/** 商品とカテゴリを並行に読む。片方が失敗しても、もう片方の結果を捨てない */
export async function loadSources(
  fileNames: { products: string; categories: string },
  options: LoadOptions,
  read: JsonReader = readFixtureText,
  onRetry?: RetryNotice
): Promise<Result<LoadedSources, LoadError[]>> {
  // 2つのファイルは互いに独立している。ループの中で await せず、同時に走らせる
  const [products, categories] = await Promise.all([
    loadText(fileNames.products, options, read, onRetry),
    loadText(fileNames.categories, options, read, onRetry),
  ]);

  // 1件目で止めない。両方だめなら両方の理由を返す（セッション18 の collectResults）
  const collected = collectResults([products, categories]);
  if (collected.kind === 'error') {
    return collected;
  }

  const [productsText, categoriesText] = collected.value;
  if (productsText === undefined || categoriesText === undefined) {
    // collectResults が成功したなら必ず2件ある。ここに来たら実装のバグ
    throw new InvariantError('読み込み結果の件数が合いません');
  }
  return ok({ productsText, categoriesText });
}
