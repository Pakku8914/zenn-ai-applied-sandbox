// 中間プロジェクト3 のテスト。
// vitest のグローバルは無効なので、describe / it / expect / vi は必ず import する。
// 実行: docker compose exec ts npx vitest run src/mid03
import { describe, expect, it, vi } from 'vitest';
import { delayWithSignal } from '../session17/async-tools';
import { calcAveragePrice } from './aggregate';
import { readFixtureText } from './load';
import type { JsonReader } from './load';
import { DEFAULT_CLI_OPTIONS, parseCliArgs, runPipeline } from './main';
import { describePipelineError, formatOutcome } from './report';
import type { CatalogItem } from './types';
import { validateProducts } from './validate';

/** 検証テストの土台。1フィールドだけ壊して「どこで落ちるか」を確かめる */
const BASE_RECORD: Record<string, unknown> = {
  id: 1,
  name: 'ラベンダーの石けん',
  price: 480,
  stock: 24,
  description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
  imageUrl: '/images/products/lavender-soap.png',
  categoryId: 1,
};

/** 指定したフィールドだけを抜いたレコードを作る（元は書き換えない） */
const without = (field: string): Record<string, unknown> =>
  Object.fromEntries(Object.entries(BASE_RECORD).filter(([key]) => key !== field));

const textOf = (records: readonly unknown[]): string => JSON.stringify(records);

/** 速いテストのための設定（再試行なし・制限時間 200ms） */
const FAST = { timeoutMs: 200, retries: 0, baseMs: 1 };

describe('検証：壊れたデータは1件ずつ理由が分かる', () => {
  it.each([
    { label: 'price が無い', record: without('price'), message: 'price がありません' },
    { label: 'price が文字列', record: { ...BASE_RECORD, price: '480' }, message: 'price の値が不正です（"480"）' },
    { label: 'stock が小数', record: { ...BASE_RECORD, stock: 1.5 }, message: 'stock の値が不正です（1.5）' },
    { label: 'stock が負', record: { ...BASE_RECORD, stock: -1 }, message: 'stock が範囲外です（-1）' },
    { label: 'name が空文字', record: { ...BASE_RECORD, name: '' }, message: 'name の値が不正です（""）' },
  ])('$label → $message', ({ record, message }) => {
    // Act
    const result = validateProducts('products.json', textOf([record]));

    // Assert: 失敗は例外ではなく戻り値なので、そのまま中身を比べられる
    expect(result.kind).toBe('error');
    if (result.kind === 'error') {
      expect(result.error.map(describePipelineError)).toEqual([
        `products.json の1件目: ${message}`,
      ]);
    }
  });

  it('在庫0は「範囲外」ではない（在庫切れは正常なデータ）', () => {
    const result = validateProducts('products.json', textOf([{ ...BASE_RECORD, stock: 0 }]));
    expect(result.kind).toBe('ok');
  });

  it('2件とも壊れていたら2件とも報告する', () => {
    const result = validateProducts(
      'products.json',
      textOf([{ ...BASE_RECORD, price: '480' }, { ...BASE_RECORD, id: 2, stock: -3 }])
    );

    expect(result.kind).toBe('error');
    if (result.kind === 'error') {
      expect(result.error).toHaveLength(2);
    }
  });

  it('JSON として壊れていたら先頭10文字を添えて失敗する', () => {
    const result = validateProducts('products.json', '[{"id": 1,');
    expect(result.kind).toBe('error');
    if (result.kind === 'error') {
      expect(result.error.map(describePipelineError)).toEqual([
        'products.json が JSON として読めません（先頭: [{"id": 1,）',
      ]);
    }
  });
});

describe('集計：平均単価の境界', () => {
  const item = (price: number): CatalogItem => ({
    id: 1,
    name: 'テスト商品',
    price,
    stock: 1,
    categoryName: 'キッチン雑貨',
  });

  it('0件でも NaN を返さない', () => {
    expect(calcAveragePrice([])).toBe(0);
  });

  it('割り切れないときは切り捨てる', () => {
    expect(calcAveragePrice([item(100), item(101)])).toBe(100);
  });
});

describe('パイプライン全体', () => {
  it('fixtures の5件からレポートを組み立てる', async () => {
    // Act: 既定の読み込み係（fixtures を読む）を使う
    const outcome = await runPipeline(DEFAULT_CLI_OPTIONS);

    // Assert: 1行ずつ比べれば、どこが崩れたかがすぐ分かる
    expect(formatOutcome(outcome)).toEqual([
      '=== 商品データ取得レポート ===',
      'バス・ボディケア: 2件 / 在庫36点 / 在庫金額 33120円',
      'キッチン雑貨: 1件 / 在庫3点 / 在庫金額 7050円',
      'ファブリック: 2件 / 在庫5点 / 在庫金額 14000円',
      '---',
      '合計: 5件 / 在庫44点 / 在庫金額 54170円',
      '平均単価: 1684円',
      '在庫切れ: リネンのふきん',
    ]);
  });

  it('読み込みに失敗しても例外ではなく Result で返る', async () => {
    // Arrange: 依存を引数で受け取る設計なので、モックライブラリは要らない
    const failingRead: JsonReader = async (fileName, signal) => {
      if (fileName === 'products.json') {
        throw new Error('ファイルが見つかりません');
      }
      return readFixtureText(fileName, signal);
    };

    // Act
    const outcome = await runPipeline({ ...DEFAULT_CLI_OPTIONS, load: FAST }, failingRead);

    // Assert
    expect(formatOutcome(outcome)).toEqual([
      '=== 取得に失敗しました（1件） ===',
      '- products.json を読み込めません（ファイルが見つかりません）',
    ]);
  });

  it('制限時間を超えると2ファイルとも中断される', async () => {
    const slowRead: JsonReader = async (fileName, signal) => {
      await delayWithSignal(200, signal);
      return readFixtureText(fileName, signal);
    };

    const outcome = await runPipeline(
      { ...DEFAULT_CLI_OPTIONS, load: { timeoutMs: 20, retries: 0, baseMs: 1 } },
      slowRead
    );

    expect(formatOutcome(outcome)).toEqual([
      '=== 取得に失敗しました（2件） ===',
      '- products.json の読み込みが 20ms を超えました',
      '- categories.json の読み込みが 20ms を超えました',
    ]);
  });

  it('1回失敗しても再試行して成功する', async () => {
    let calls = 0;
    const flakyRead: JsonReader = async (fileName, signal) => {
      if (fileName === 'products.json') {
        calls += 1;
        if (calls === 1) {
          throw new Error('一時的な失敗');
        }
      }
      return readFixtureText(fileName, signal);
    };
    const onRetry = vi.fn();

    const outcome = await runPipeline(
      { ...DEFAULT_CLI_OPTIONS, load: { timeoutMs: 200, retries: 1, baseMs: 1 } },
      flakyRead,
      onRetry
    );

    expect(outcome.kind).toBe('ok');
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry).toHaveBeenCalledWith('products.json', 1, 1);
  });

  it('カテゴリマスタに無い商品は変換で失敗する', async () => {
    const partialCategories: JsonReader = async (fileName, signal) =>
      fileName === 'categories.json'
        ? JSON.stringify([{ id: 1, name: 'バス・ボディケア', slug: 'bath-body' }])
        : readFixtureText(fileName, signal);

    const outcome = await runPipeline(
      { ...DEFAULT_CLI_OPTIONS, load: FAST },
      partialCategories
    );

    expect(formatOutcome(outcome)).toEqual([
      '=== 取得に失敗しました（3件） ===',
      '- 「マグカップ」のカテゴリ（categoryId: 2）がマスタにありません',
      '- 「リネンのふきん」のカテゴリ（categoryId: 3）がマスタにありません',
      '- 「コットンのトートバッグ」のカテゴリ（categoryId: 3）がマスタにありません',
    ]);
  });
});

describe('引数の解析', () => {
  it('既定では fixtures の products.json を読む', () => {
    const parsed = parseCliArgs([]);
    expect(parsed).toEqual({ kind: 'ok', value: DEFAULT_CLI_OPTIONS });
  });

  it('--products で読むファイルを差し替えられる', () => {
    const parsed = parseCliArgs(['--products', 'products-broken.json']);
    expect(parsed.kind).toBe('ok');
    if (parsed.kind === 'ok') {
      expect(parsed.value.productsFile).toBe('products-broken.json');
    }
  });

  it('--timeout を変えても既定の設定は書き換わらない', () => {
    parseCliArgs(['--timeout', '50']);
    expect(DEFAULT_CLI_OPTIONS.load.timeoutMs).toBe(1000);
  });

  it.each([
    { args: ['--unknown', 'x'], message: '知らないオプションです: --unknown' },
    { args: ['--timeout', '0'], message: '--timeout には正の整数を指定してください（0）' },
    { args: ['--products'], message: '--products に値がありません' },
  ])('$args → $message', ({ args, message }) => {
    expect(parseCliArgs(args)).toEqual({ kind: 'error', error: message });
  });
});
