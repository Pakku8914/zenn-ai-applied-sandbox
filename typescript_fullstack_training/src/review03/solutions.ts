// 復習03 の解答本体。セッション16〜19 の部品を組み合わせて、
// 「非同期の失敗を型で扱い、テストで固める」形にまとめている。
import { isAbortLike, retryWithBackoff, withTimeout } from '../session17/async-tools';
import { loadJsonText, reserveStockStub } from '../session17/catalog';
import type { Category, Product } from '../session17/catalog';
import { DataError, tryCatch } from './shared';
import type { Result } from './shared';

// ---------------------------------------------------------------------------
// 問題1：危険な catch を直す（S18・S16・S12）
// ---------------------------------------------------------------------------

export type LoadContext = { userId: number; token: string; endpoint: string };

/** catch で受けた unknown を、人が読める1行に変換する */
export function describeError(error: unknown): string {
  if (error instanceof Error) {
    const head = `${error.name}: ${error.message}`;
    // cause に元のエラーが入っていれば、それも添える（原因が消えないようにする）
    if (error.cause instanceof Error) {
      return `${head} / 原因: ${error.cause.name}: ${error.cause.message}`;
    }
    return head;
  }
  if (typeof error === 'string') {
    return `文字列が投げられました: ${error}`;
  }
  return `不明なエラー: ${JSON.stringify(error)}`;
}

/** ログに出してよい項目だけを選び直す。token は絶対に含めない */
export function toLogContext(context: LoadContext): { userId: number; endpoint: string } {
  return { userId: context.userId, endpoint: context.endpoint };
}

/** ログの1行も純粋関数にしておくと、文言そのものをテストできる */
export function formatLogLine(context: LoadContext, error: unknown): string {
  return `[取得失敗] ${describeError(error)} / ${JSON.stringify(toLogContext(context))}`;
}

// 実行中の件数。finally で必ず戻すことを確かめるために持っている
let activeLoads = 0;

export function getActiveLoads(): number {
  return activeLoads;
}

/** 予測できる失敗は Result で返す。finally には return を書かない */
export async function loadCount(
  task: () => Promise<readonly string[]>
): Promise<Result<number, string>> {
  activeLoads += 1;

  try {
    const items = await task();
    return { kind: 'ok', value: items.length };
  } catch (error: unknown) {
    return { kind: 'error', error: describeError(error) };
  } finally {
    // 後片付けだけを書く。ここで return すると try / catch の戻り値が捨てられる
    activeLoads -= 1;
  }
}

// ---------------------------------------------------------------------------
// 問題4：unknown な JSON を型ガードで絞り込み、失敗を Result で返す
// （S16・S12・S13・S18）
// ---------------------------------------------------------------------------

export type ParseError =
  | { kind: 'invalid_json'; text: string }
  | { kind: 'not_array' }
  | { kind: 'missing_field'; index: number; field: string }
  | { kind: 'invalid_value'; index: number; field: string; value: unknown };

export function formatParseError(error: ParseError): string {
  switch (error.kind) {
    case 'invalid_json':
      return `JSON として読めません（先頭: ${error.text.slice(0, 10)}）`;
    case 'not_array':
      return '配列ではありません';
    case 'missing_field':
      return `${error.index + 1}件目の ${error.field} がありません`;
    case 'invalid_value':
      return (
        `${error.index + 1}件目の ${error.field} の値が不正です` +
        `（${JSON.stringify(error.value)}）`
      );
    default: {
      // 種類を増やしたらここが型エラーになる（網羅性チェック）
      const _exhaustive: never = error;
      throw new Error(`未知の解析エラーです: ${JSON.stringify(_exhaustive)}`);
    }
  }
}

/**
 * unknown を「キーで引ける入れ物」に変換する。
 * as で嘘の型を付ける代わりに Map に詰め替えるので、読み取りは unknown のまま保たれる。
 */
function toRecord(value: unknown): Map<string, unknown> | undefined {
  if (typeof value !== 'object' || value === null) {
    return undefined;
  }
  const entries: [string, unknown][] = Object.entries(value);
  return new Map(entries);
}

function requireNumber(
  record: Map<string, unknown>,
  field: string,
  index: number
): Result<number, ParseError> {
  if (!record.has(field)) {
    return { kind: 'error', error: { kind: 'missing_field', index, field } };
  }
  const value = record.get(field);
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    return { kind: 'error', error: { kind: 'invalid_value', index, field, value } };
  }
  return { kind: 'ok', value };
}

function requireString(
  record: Map<string, unknown>,
  field: string,
  index: number
): Result<string, ParseError> {
  if (!record.has(field)) {
    return { kind: 'error', error: { kind: 'missing_field', index, field } };
  }
  const value = record.get(field);
  if (typeof value !== 'string' || value.length === 0) {
    return { kind: 'error', error: { kind: 'invalid_value', index, field, value } };
  }
  return { kind: 'ok', value };
}

export function toProductItem(value: unknown, index: number): Result<Product, ParseError> {
  const record = toRecord(value);
  if (record === undefined) {
    return { kind: 'error', error: { kind: 'invalid_value', index, field: '(要素そのもの)', value } };
  }

  const id = requireNumber(record, 'id', index);
  if (id.kind === 'error') {
    return id;
  }
  const name = requireString(record, 'name', index);
  if (name.kind === 'error') {
    return name;
  }
  const price = requireNumber(record, 'price', index);
  if (price.kind === 'error') {
    return price;
  }
  const stock = requireNumber(record, 'stock', index);
  if (stock.kind === 'error') {
    return stock;
  }
  const description = requireString(record, 'description', index);
  if (description.kind === 'error') {
    return description;
  }
  const imageUrl = requireString(record, 'imageUrl', index);
  if (imageUrl.kind === 'error') {
    return imageUrl;
  }
  const categoryId = requireNumber(record, 'categoryId', index);
  if (categoryId.kind === 'error') {
    return categoryId;
  }

  return {
    kind: 'ok',
    value: {
      id: id.value,
      name: name.value,
      price: price.value,
      stock: stock.value,
      description: description.value,
      imageUrl: imageUrl.value,
      categoryId: categoryId.value,
    },
  };
}

export function toCategoryItem(value: unknown, index: number): Result<Category, ParseError> {
  const record = toRecord(value);
  if (record === undefined) {
    return { kind: 'error', error: { kind: 'invalid_value', index, field: '(要素そのもの)', value } };
  }

  const id = requireNumber(record, 'id', index);
  if (id.kind === 'error') {
    return id;
  }
  const name = requireString(record, 'name', index);
  if (name.kind === 'error') {
    return name;
  }
  const slug = requireString(record, 'slug', index);
  if (slug.kind === 'error') {
    return slug;
  }

  return { kind: 'ok', value: { id: id.value, name: name.value, slug: slug.value } };
}

/** JSON テキストを配列として検証する。要素の検証方法は呼ぶ側が渡す（ジェネリクス） */
export function parseArray<T>(
  text: string,
  toItem: (value: unknown, index: number) => Result<T, ParseError>
): Result<T[], ParseError> {
  let parsed: unknown;

  try {
    parsed = JSON.parse(text);
  } catch {
    // JSON.parse は any を返すが、unknown の変数で受けているので any は外に漏れない
    return { kind: 'error', error: { kind: 'invalid_json', text } };
  }

  if (!Array.isArray(parsed)) {
    return { kind: 'error', error: { kind: 'not_array' } };
  }

  const values: readonly unknown[] = parsed;
  const items: T[] = [];

  for (let index = 0; index < values.length; index += 1) {
    const item = toItem(values[index], index);
    if (item.kind === 'error') {
      return item;
    }
    items.push(item.value);
  }

  return { kind: 'ok', value: items };
}

export function parseProducts(text: string): Result<Product[], ParseError> {
  return parseArray(text, toProductItem);
}

export function parseCategories(text: string): Result<Category[], ParseError> {
  return parseArray(text, toCategoryItem);
}

// ---------------------------------------------------------------------------
// 問題5：ループの中の await をやめ、1件失敗しても他を捨てない（S17・S18・S13）
// ---------------------------------------------------------------------------

export type ReservationOutcome = { product: Product; result: Result<string, string> };

/** 悪い例：1件ずつ待つので遅く、1件でも失敗すると途中で止まる */
export async function reserveAllSequential(
  products: readonly Product[],
  reserve: (product: Product) => Promise<string> = reserveStockStub
): Promise<string[]> {
  const messages: string[] = [];

  for (const product of products) {
    messages.push(await reserve(product));
  }

  return messages;
}

/** 良い例：全件を同時に走らせ、成功と失敗を Result に詰め替えて全部返す */
export async function reserveAllSettled(
  products: readonly Product[],
  reserve: (product: Product) => Promise<string> = reserveStockStub
): Promise<ReservationOutcome[]> {
  // map の中で await しない。Promise の配列を作ってから1回だけ待つ
  const settled = await Promise.allSettled(products.map((product) => reserve(product)));

  return products.map((product, index): ReservationOutcome => {
    const outcome = settled[index];
    if (outcome === undefined) {
      return { product, result: { kind: 'error', error: '結果が取得できませんでした' } };
    }
    if (outcome.status === 'fulfilled') {
      return { product, result: { kind: 'ok', value: outcome.value } };
    }
    return { product, result: { kind: 'error', error: describeError(outcome.reason) } };
  });
}

export function summarizeReservations(outcomes: readonly ReservationOutcome[]): string[] {
  const succeeded: string[] = [];
  const failed: string[] = [];

  for (const outcome of outcomes) {
    if (outcome.result.kind === 'ok') {
      succeeded.push(outcome.product.name);
    } else {
      failed.push(`${outcome.product.name}（${outcome.result.error}）`);
    }
  }

  return [
    `成功${succeeded.length}件 / 失敗${failed.length}件`,
    `成功: ${succeeded.length === 0 ? '(なし)' : succeeded.join(' / ')}`,
    `失敗: ${failed.length === 0 ? '(なし)' : failed.join(' / ')}`,
  ];
}

// ---------------------------------------------------------------------------
// 問題6：タイムアウトとリトライを組み合わせる（S17・S18・S19）
// ---------------------------------------------------------------------------

export type LoadOptions = {
  /** 1回の試行に許す時間（ミリ秒） */
  timeoutMs: number;
  /** 追加で試す回数（合計の試行回数は retries + 1 回） */
  retries: number;
  /** 1回目の待ち時間（ミリ秒）。2回目以降は2倍ずつ増える */
  baseMs: number;
};

export async function loadWithRetry<T>(
  task: (signal: AbortSignal) => Promise<T>,
  options: LoadOptions,
  onRetry?: (attempt: number, waitMs: number, error: unknown) => void
): Promise<Result<T, string>> {
  const outcome = await tryCatch(() =>
    retryWithBackoff(
      () => withTimeout(task, options.timeoutMs),
      { retries: options.retries, baseMs: options.baseMs },
      onRetry
    )
  );

  if (outcome.kind === 'ok') {
    return outcome;
  }
  // 中断による失敗だけは、環境ごとに文言が違うので自分の言葉に置き換える
  if (isAbortLike(outcome.error)) {
    return { kind: 'error', error: `制限時間 ${options.timeoutMs}ms を超えました` };
  }
  return { kind: 'error', error: describeError(outcome.error) };
}

// ---------------------------------------------------------------------------
// 問題7：読み込み → 検証 → 変換 → 集計 → レポート（S16〜S19 の総合）
// ---------------------------------------------------------------------------

/** JSON を読む係。signal を受け取れる形にしておくと、途中で中断できる */
export type JsonReader = (fileName: string, signal: AbortSignal) => Promise<string>;

export type ReportRow = { categoryName: string; count: number; stockValue: number };

export function summarizeByCategory(
  products: readonly Product[],
  categories: readonly Category[]
): ReportRow[] {
  return categories.map((category) => {
    const items = products.filter((product) => product.categoryId === category.id);
    return {
      categoryName: category.name,
      count: items.length,
      stockValue: items.reduce((total, item) => total + item.price * item.stock, 0),
    };
  });
}

export function formatReport(
  products: readonly Product[],
  categories: readonly Category[]
): string[] {
  const rows = summarizeByCategory(products, categories);
  const soldOut = products.filter((product) => product.stock <= 0).map((product) => product.name);

  return [
    '=== 商品カタログ レポート ===',
    ...rows.map((row) => `${row.categoryName}: ${row.count}件 / 在庫金額 ${row.stockValue}円`),
    `在庫切れ: ${soldOut.length === 0 ? '(なし)' : soldOut.join(' / ')}`,
    `合計: ${products.length}件 / ${rows.reduce((total, row) => total + row.stockValue, 0)}円`,
  ];
}

export async function loadProductReport(
  options: LoadOptions,
  read: JsonReader = loadJsonText
): Promise<Result<string[], string>> {
  const loaded = await loadWithRetry(async (signal): Promise<[string, string]> => {
    // 2つのファイルは互いに独立しているので並行に読む
    const texts = await Promise.all([
      readOrWrap('products.json', read, signal),
      readOrWrap('categories.json', read, signal),
    ]);

    if (signal.aborted) {
      // 読み終わっていても、すでに中断されていたら結果を捨てる
      throw signal.reason;
    }
    return [texts[0], texts[1]];
  }, options);

  if (loaded.kind === 'error') {
    return loaded;
  }

  const [productsText, categoriesText] = loaded.value;

  const products = parseProducts(productsText);
  if (products.kind === 'error') {
    return { kind: 'error', error: formatParseError(products.error) };
  }

  const categories = parseCategories(categoriesText);
  if (categories.kind === 'error') {
    return { kind: 'error', error: formatParseError(categories.error) };
  }

  return { kind: 'ok', value: formatReport(products.value, categories.value) };
}

/** 読み込みの失敗を DataError に包み直す。元のエラーは cause に残す */
async function readOrWrap(
  fileName: string,
  read: JsonReader,
  signal: AbortSignal
): Promise<string> {
  try {
    return await read(fileName, signal);
  } catch (error: unknown) {
    if (isAbortLike(error)) {
      // 中断は「失敗」ではなく「やめた」なので、包み直さずそのまま上へ渡す
      throw error;
    }
    throw new DataError(`${fileName} を読み込めません`, { cause: error });
  }
}
