// エントリポイント。画面への出力（console.log / console.error）を書いてよいのは
// このファイルだけ。他のモジュールは値を返すだけにしてある。
//
// 実行: docker compose exec ts npx tsx src/mid03/main.ts

import { err, ok } from '../session18/result';
import type { Result } from '../session18/result';
import { buildReport } from './aggregate';
import { DEFAULT_LOAD_OPTIONS, loadSources, readFixtureText } from './load';
import type { JsonReader, LoadOptions, RetryNotice } from './load';
import { formatOutcome } from './report';
import { toCatalogItems } from './transform';
import type { PipelineError, ProductReport } from './types';
import { validateCategories, validateProducts } from './validate';

export type CliOptions = {
  productsFile: string;
  categoriesFile: string;
  load: LoadOptions;
};

export const DEFAULT_CLI_OPTIONS: CliOptions = {
  productsFile: 'products.json',
  categoriesFile: 'categories.json',
  load: DEFAULT_LOAD_OPTIONS,
};

/** コマンドライン引数を読む。おかしければ理由を Result で返す（ここでも throw しない） */
export function parseCliArgs(args: readonly string[]): Result<CliOptions, string> {
  let options: CliOptions = DEFAULT_CLI_OPTIONS;

  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    const value = args[index + 1];

    if (flag === undefined) {
      break;
    }
    if (value === undefined) {
      return err<string>(`${flag} に値がありません`);
    }

    if (flag === '--products') {
      options = { ...options, productsFile: value };
    } else if (flag === '--categories') {
      options = { ...options, categoriesFile: value };
    } else if (flag === '--timeout') {
      const limitMs = Number(value);
      if (!Number.isInteger(limitMs) || limitMs <= 0) {
        return err<string>(`--timeout には正の整数を指定してください（${value}）`);
      }
      options = { ...options, load: { ...options.load, timeoutMs: limitMs } };
    } else {
      return err<string>(`知らないオプションです: ${flag}`);
    }
  }

  return ok(options);
}

/**
 * 読み込み → 検証 → 変換 → 集計 を順につなぐ。
 * 画面出力はしないので、この関数はそのままテストできる。
 */
export async function runPipeline(
  options: CliOptions,
  read: JsonReader = readFixtureText,
  onRetry?: RetryNotice
): Promise<Result<ProductReport, PipelineError[]>> {
  // 1. 読み込み（非同期・制限時間つき）
  const loaded = await loadSources(
    { products: options.productsFile, categories: options.categoriesFile },
    options.load,
    read,
    onRetry
  );
  if (loaded.kind === 'error') {
    return loaded;
  }

  // 2. 検証（unknown → Product / Category）
  const products = validateProducts(options.productsFile, loaded.value.productsText);
  if (products.kind === 'error') {
    return products;
  }
  const categories = validateCategories(options.categoriesFile, loaded.value.categoriesText);
  if (categories.kind === 'error') {
    return categories;
  }

  // 3. 変換（カテゴリ名の紐づけ）
  const items = toCatalogItems(products.value, categories.value);
  if (items.kind === 'error') {
    return items;
  }

  // 4. 集計（カテゴリの表示順はマスタの並びに合わせる）
  const categoryNames = categories.value.map((category) => category.name);
  return ok(buildReport(items.value, categoryNames));
}

/** 画面に出す係。終了コードを返す（0 = 成功 / 1 = 取得失敗 / 2 = 引数が不正） */
export async function main(argv: readonly string[]): Promise<number> {
  const parsed = parseCliArgs(argv);
  if (parsed.kind === 'error') {
    console.error(`引数が不正です: ${parsed.error}`);
    console.error('使い方: npx tsx src/mid03/main.ts [--products <file>] [--timeout <ms>]');
    return 2;
  }

  const outcome = await runPipeline(parsed.value, readFixtureText, (fileName, attempt, waitMs) => {
    // 再試行の通知は標準エラー出力へ。レポート本体（標準出力）を汚さない
    console.error(`[再試行] ${fileName} の${attempt}回目が失敗 → ${waitMs}ms 待って再試行します`);
  });

  for (const line of formatOutcome(outcome)) {
    console.log(line);
  }
  return outcome.kind === 'ok' ? 0 : 1;
}

// このファイルを直接実行したときだけ動かす。
// 他のファイルから import されたときは実行されない（テストが勝手に走らないようにする）。
const entryPoint = process.argv[1] ?? '';
if (entryPoint.endsWith('main.ts')) {
  process.exitCode = await main(process.argv.slice(2));
}
