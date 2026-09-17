// 読み込んだテキストを検証するモジュール。
// unknown から始めて、検査を通ったものだけを Product / Category として扱う。
// 型アサーション（as）は使わない。嘘の型を付けた瞬間に、この層の意味が消えるため。

import { collectResults, err, ok } from '../session18/result';
import type { Result } from '../session18/result';
import type { Category, Product, ValidationError } from './types';

/** 「どのファイルの何件目のどのフィールドか」を毎回書かずに済むよう、まとめて持つ */
type FieldPlace = { fileName: string; index: number; field: string };

/**
 * unknown を「キーで引ける入れ物」に変える。
 * as で型を付け替える代わりに Map に詰め替えるので、値は unknown のまま保たれる。
 */
function toRecord(value: unknown): Map<string, unknown> | undefined {
  if (typeof value !== 'object' || value === null) {
    return undefined;
  }
  const entries: [string, unknown][] = Object.entries(value);
  return new Map(entries);
}

/** 空でない文字列であることを確かめる */
function requireString(
  record: Map<string, unknown>,
  place: FieldPlace
): Result<string, ValidationError> {
  if (!record.has(place.field)) {
    return err<ValidationError>({ kind: 'missing_field', ...place });
  }
  const value = record.get(place.field);
  if (typeof value !== 'string' || value.length === 0) {
    return err<ValidationError>({ kind: 'invalid_type', ...place, value });
  }
  return ok(value);
}

/** min 以上の整数であることを確かめる。範囲は型では書けないので実行時に見る */
function requireInteger(
  record: Map<string, unknown>,
  place: FieldPlace,
  min: number
): Result<number, ValidationError> {
  if (!record.has(place.field)) {
    return err<ValidationError>({ kind: 'missing_field', ...place });
  }
  const value = record.get(place.field);
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    return err<ValidationError>({ kind: 'invalid_type', ...place, value });
  }
  if (value < min) {
    return err<ValidationError>({ kind: 'out_of_range', ...place, value });
  }
  return ok(value);
}

/** 1件を Product にする。7フィールドすべてを検査する */
export function toProduct(
  fileName: string,
  value: unknown,
  index: number
): Result<Product, ValidationError> {
  const record = toRecord(value);
  if (record === undefined) {
    const place = { fileName, index, field: '(要素そのもの)' };
    return err<ValidationError>({ kind: 'invalid_type', ...place, value });
  }

  // 「どのフィールドか」だけを渡せば済むように、場所を閉じ込めた小さな道具を作る
  const str = (field: string): Result<string, ValidationError> =>
    requireString(record, { fileName, index, field });
  const int = (field: string, min: number): Result<number, ValidationError> =>
    requireInteger(record, { fileName, index, field }, min);

  const id = int('id', 1);
  if (id.kind === 'error') return id;
  const name = str('name');
  if (name.kind === 'error') return name;
  const price = int('price', 0);
  if (price.kind === 'error') return price;
  const stock = int('stock', 0);
  if (stock.kind === 'error') return stock;
  const description = str('description');
  if (description.kind === 'error') return description;
  const imageUrl = str('imageUrl');
  if (imageUrl.kind === 'error') return imageUrl;
  const categoryId = int('categoryId', 1);
  if (categoryId.kind === 'error') return categoryId;

  return ok({
    id: id.value,
    name: name.value,
    price: price.value,
    stock: stock.value,
    description: description.value,
    imageUrl: imageUrl.value,
    categoryId: categoryId.value,
  });
}

/** 1件を Category にする */
export function toCategory(
  fileName: string,
  value: unknown,
  index: number
): Result<Category, ValidationError> {
  const record = toRecord(value);
  if (record === undefined) {
    const place = { fileName, index, field: '(要素そのもの)' };
    return err<ValidationError>({ kind: 'invalid_type', ...place, value });
  }

  const id = requireInteger(record, { fileName, index, field: 'id' }, 1);
  if (id.kind === 'error') return id;
  const name = requireString(record, { fileName, index, field: 'name' });
  if (name.kind === 'error') return name;
  const slug = requireString(record, { fileName, index, field: 'slug' });
  if (slug.kind === 'error') return slug;

  return ok({ id: id.value, name: name.value, slug: slug.value });
}

/**
 * JSON テキストを配列として検証する。要素の検査方法は呼ぶ側が渡す（ジェネリクス）。
 * 復習03 の parseArray に fileName を足し、失敗を配列で返すようにしたもの。
 */
export function parseArray<T>(
  fileName: string,
  text: string,
  toItem: (fileName: string, value: unknown, index: number) => Result<T, ValidationError>
): Result<T[], ValidationError[]> {
  let parsed: unknown;

  try {
    parsed = JSON.parse(text);
  } catch {
    // JSON.parse は any を返すが、unknown の変数で受けているので any は外に漏れない
    return err<ValidationError[]>([
      { kind: 'invalid_json', fileName, head: text.trim().slice(0, 10) },
    ]);
  }

  if (!Array.isArray(parsed)) {
    return err<ValidationError[]>([{ kind: 'not_array', fileName }]);
  }

  const values: readonly unknown[] = parsed;
  // 1件目で止めない。壊れている行をまとめて報告したほうが、直す回数が減る
  return collectResults(values.map((value, index) => toItem(fileName, value, index)));
}

export function validateProducts(
  fileName: string,
  text: string
): Result<Product[], ValidationError[]> {
  return parseArray(fileName, text, toProduct);
}

export function validateCategories(
  fileName: string,
  text: string
): Result<Category[], ValidationError[]> {
  return parseArray(fileName, text, toCategory);
}
