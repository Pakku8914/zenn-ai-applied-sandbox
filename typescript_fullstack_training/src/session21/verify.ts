// セッション21「Next.js App Routerの基礎」の検証スクリプト。
//
// この章の画面は web フォルダ側（Next.js / React）にあり、src 側の tsconfig には
// DOM の型が無いため、ここから web 側のモジュールを import することはできない。
// そこで、章で切り出した「純粋なロジック」だけを、このファイルに同じ実装として置き、
// 本文・練習問題・解答に書いた期待値と一致するかを確かめる。
// 対応する web 側の実装は lib フォルダの product-query.ts と api-error.ts。
// 画面そのものは verify-all.sh の最後にある web の型チェックと next build が検証する。
//
// 実行: docker compose exec ts npx tsx src/session21/verify.ts

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label}\n--- 期待値 ---\n${expected}\n--- 実際 ---\n${actual}`);
    failedCount += 1;
  }
}

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ---------------------------------------------------------------------------
// 検証用のデータ。
// 並べ替えと絞り込みは name / price / stock / categoryId しか見ないので、
// description と imageUrl を省いた ProductSummary で確かめる（値はマスタと同じ）。
// ---------------------------------------------------------------------------
type ProductSummary = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryId: number;
};

const PRODUCTS: readonly ProductSummary[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

const CATEGORY_SLUGS = ['bath-body', 'kitchen', 'fabric'] as const;

function findCategoryIdBySlug(slug: string): number | undefined {
  const index = (CATEGORY_SLUGS as readonly string[]).indexOf(slug);

  return index === -1 ? undefined : index + 1;
}

/** id だけを並べた文字列にして比較しやすくする */
function toIdList(products: readonly ProductSummary[]): string {
  return products.map((product) => product.id).join(',');
}

// ---------------------------------------------------------------------------
// 本文：URL の文字列を解釈する（web 側の lib/product-query.ts と同じ実装）
// ---------------------------------------------------------------------------
const PAGE_SIZE = 3;

type SortKey = 'price-asc' | 'price-desc' | 'name-asc';

const SORT_KEYS = ['price-asc', 'price-desc', 'name-asc'] as const;
const DEFAULT_SORT: SortKey = 'price-asc';

type RawSearchParams = { [key: string]: string | string[] | undefined };

type ProductQuery = {
  categorySlug: string | null;
  sort: SortKey;
  page: number;
};

type Pagination = {
  page: number;
  totalPages: number;
  skip: number;
  take: number;
};

function parseProductId(raw: string): number | null {
  if (!/^[1-9][0-9]*$/.test(raw)) {
    return null;
  }

  const id = Number(raw);

  return Number.isSafeInteger(id) ? id : null;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function isSortKey(value: string): value is SortKey {
  return (SORT_KEYS as readonly string[]).includes(value);
}

function parseCategorySlug(value: string | string[] | undefined): string | null {
  const slug = firstValue(value);

  if (slug === undefined || findCategoryIdBySlug(slug) === undefined) {
    return null;
  }

  return slug;
}

function parseSort(value: string | string[] | undefined): SortKey {
  const sort = firstValue(value);

  return sort !== undefined && isSortKey(sort) ? sort : DEFAULT_SORT;
}

function parsePage(value: string | string[] | undefined): number {
  const page = Number(firstValue(value) ?? '1');

  return Number.isInteger(page) && page >= 1 ? page : 1;
}

function parseProductQuery(raw: RawSearchParams): ProductQuery {
  return {
    categorySlug: parseCategorySlug(raw['category']),
    sort: parseSort(raw['sort']),
    page: parsePage(raw['page']),
  };
}

function calcPagination(
  totalCount: number,
  requestedPage: number,
  pageSize: number = PAGE_SIZE
): Pagination {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const page = Math.min(Math.max(requestedPage, 1), totalPages);

  return { page, totalPages, skip: (page - 1) * pageSize, take: pageSize };
}

function compareBy(sort: SortKey): (a: ProductSummary, b: ProductSummary) => number {
  switch (sort) {
    case 'price-asc':
      return (a, b) => a.price - b.price;
    case 'price-desc':
      return (a, b) => b.price - a.price;
    case 'name-asc':
      return (a, b) => a.name.localeCompare(b.name, 'ja');
    default: {
      const unreachable: never = sort;

      throw new Error(`未知の並べ替えです: ${String(unreachable)}`);
    }
  }
}

function filterAndSortProducts(
  products: readonly ProductSummary[],
  categoryId: number | null,
  sort: SortKey
): ProductSummary[] {
  const filtered =
    categoryId === null
      ? [...products]
      : products.filter((product) => product.categoryId === categoryId);

  return filtered.sort(compareBy(sort));
}

function buildProductsHref(query: ProductQuery, page: number): string {
  const params = new URLSearchParams();

  if (query.categorySlug !== null) {
    params.set('category', query.categorySlug);
  }
  if (query.sort !== DEFAULT_SORT) {
    params.set('sort', query.sort);
  }
  if (page > 1) {
    params.set('page', String(page));
  }

  const queryString = params.toString();

  return queryString === '' ? '/products' : `/products?${queryString}`;
}

// ---------------------------------------------------------------------------
// 本文：失敗をステータスコードに写す（web 側の lib/api-error.ts と同じ実装）
// ---------------------------------------------------------------------------
type ApiFailure =
  | { kind: 'invalid_id'; raw: string }
  | { kind: 'unknown_category'; slug: string }
  | { kind: 'product_not_found'; productId: number };

function describeFailure(failure: ApiFailure): { status: number; message: string } {
  switch (failure.kind) {
    case 'invalid_id':
      return { status: 400, message: `商品IDの形式が正しくありません: ${failure.raw}` };
    case 'unknown_category':
      return { status: 400, message: `存在しないカテゴリです: ${failure.slug}` };
    case 'product_not_found':
      return { status: 404, message: `商品が見つかりません: ${failure.productId}` };
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

// ---------------------------------------------------------------------------
// 本文4節：params の文字列を商品 ID にする
// ---------------------------------------------------------------------------
const productIdCases: { raw: string; expected: number | null }[] = [
  { raw: '1', expected: 1 },
  { raw: '3', expected: 3 },
  { raw: '999', expected: 999 },
  { raw: '0', expected: null },
  { raw: '007', expected: null },
  { raw: '-1', expected: null },
  { raw: '1.5', expected: null },
  { raw: 'abc', expected: null },
  { raw: '', expected: null },
  { raw: ' 3', expected: null },
  { raw: '3abc', expected: null },
  { raw: '99999999999999999999', expected: null },
];

for (const { raw, expected } of productIdCases) {
  checkString(`本文4節: parseProductId("${raw}")`, String(parseProductId(raw)), String(expected));
}

// ---------------------------------------------------------------------------
// 本文5節：searchParams の解釈（不正な値は既定値に落とす）
// ---------------------------------------------------------------------------
checkJson('本文5節: category と page', parseProductQuery({ category: 'kitchen', page: '2' }), {
  categorySlug: 'kitchen',
  sort: 'price-asc',
  page: 2,
});
checkJson('本文5節: 指定なし', parseProductQuery({}), {
  categorySlug: null,
  sort: 'price-asc',
  page: 1,
});
checkJson('本文5節: 存在しないカテゴリ', parseProductQuery({ category: 'sweets' }), {
  categorySlug: null,
  sort: 'price-asc',
  page: 1,
});
checkJson('本文5節: 同じキーが2回', parseProductQuery({ category: ['kitchen', 'fabric'] }), {
  categorySlug: 'kitchen',
  sort: 'price-asc',
  page: 1,
});
checkJson('本文5節: 並べ替えの指定', parseProductQuery({ sort: 'price-desc' }), {
  categorySlug: null,
  sort: 'price-desc',
  page: 1,
});

const invalidPageCases = ['0', '-3', 'abc', '2.5', ''];

for (const page of invalidPageCases) {
  checkNumber(`本文5節: 不正なページ番号 "${page}"`, parseProductQuery({ page }).page, 1);
}
checkString('本文5節: 不正な並べ替え', parseProductQuery({ sort: 'random' }).sort, 'price-asc');

// ---------------------------------------------------------------------------
// 本文5節：ページ送りの計算（1ページ3件）
// ---------------------------------------------------------------------------
checkJson('本文5節: 5件の1ページ目', calcPagination(5, 1), {
  page: 1,
  totalPages: 2,
  skip: 0,
  take: 3,
});
checkJson('本文5節: 5件の2ページ目', calcPagination(5, 2), {
  page: 2,
  totalPages: 2,
  skip: 3,
  take: 3,
});
checkJson('本文5節: 範囲外のページは最後のページに寄せる', calcPagination(5, 99), {
  page: 2,
  totalPages: 2,
  skip: 3,
  take: 3,
});
checkJson('本文5節: 0件でも1ページ扱い', calcPagination(0, 1), {
  page: 1,
  totalPages: 1,
  skip: 0,
  take: 3,
});
checkJson('本文5節: ちょうど3件', calcPagination(3, 1), {
  page: 1,
  totalPages: 1,
  skip: 0,
  take: 3,
});

// ---------------------------------------------------------------------------
// 本文5節：絞り込みと並べ替え
// ---------------------------------------------------------------------------
checkString(
  '本文5節: 全件を価格の安い順',
  toIdList(filterAndSortProducts(PRODUCTS, null, 'price-asc')),
  '1,4,2,3,5'
);
checkString(
  '本文5節: 全件を価格の高い順',
  toIdList(filterAndSortProducts(PRODUCTS, null, 'price-desc')),
  '5,3,2,4,1'
);
checkString(
  '本文5節: 全件を名前順',
  toIdList(filterAndSortProducts(PRODUCTS, null, 'name-asc')),
  '5,2,3,1,4'
);
checkString(
  '本文5節: バス・ボディケアだけ',
  toIdList(filterAndSortProducts(PRODUCTS, 1, 'price-asc')),
  '1,2'
);
checkString(
  '本文5節: キッチン雑貨だけ',
  toIdList(filterAndSortProducts(PRODUCTS, 2, 'price-asc')),
  '3'
);
checkString(
  '本文5節: ファブリックだけ',
  toIdList(filterAndSortProducts(PRODUCTS, 3, 'price-asc')),
  '4,5'
);
checkString(
  '本文5節: 該当なし',
  toIdList(filterAndSortProducts(PRODUCTS, 99, 'price-asc')),
  ''
);
checkString('本文5節: 元の配列は並べ替えられていない', toIdList(PRODUCTS), '1,2,3,4,5');

// 一覧に実際に表示される3件（1ページ目）と2件（2ページ目）
const allSorted = filterAndSortProducts(PRODUCTS, null, 'price-asc');
const firstPage = calcPagination(allSorted.length, 1);
const secondPage = calcPagination(allSorted.length, 2);

checkString(
  '本文5節: 1ページ目に出る商品',
  toIdList(allSorted.slice(firstPage.skip, firstPage.skip + firstPage.take)),
  '1,4,2'
);
checkString(
  '本文5節: 2ページ目に出る商品',
  toIdList(allSorted.slice(secondPage.skip, secondPage.skip + secondPage.take)),
  '3,5'
);

// ---------------------------------------------------------------------------
// 本文5節：絞り込みを保ったままページ番号を差し替えるリンク
// ---------------------------------------------------------------------------
const defaultQuery: ProductQuery = { categorySlug: null, sort: 'price-asc', page: 1 };

checkString('本文5節: 既定の1ページ目', buildProductsHref(defaultQuery, 1), '/products');
checkString(
  '本文5節: 2ページ目へ',
  buildProductsHref(defaultQuery, 2),
  '/products?page=2'
);
checkString(
  '本文5節: カテゴリを保って2ページ目へ',
  buildProductsHref({ ...defaultQuery, categorySlug: 'kitchen' }, 2),
  '/products?category=kitchen&page=2'
);
checkString(
  '本文5節: 並べ替えだけ指定',
  buildProductsHref({ ...defaultQuery, sort: 'price-desc' }, 1),
  '/products?sort=price-desc'
);
checkString(
  '本文5節: 3つとも指定',
  buildProductsHref({ categorySlug: 'fabric', sort: 'name-asc', page: 3 }, 3),
  '/products?category=fabric&sort=name-asc&page=3'
);

// ---------------------------------------------------------------------------
// 本文8節：ルートハンドラが返すステータスコードとメッセージ
// ---------------------------------------------------------------------------
const failureCases: { failure: ApiFailure; status: number; message: string }[] = [
  {
    failure: { kind: 'invalid_id', raw: 'abc' },
    status: 400,
    message: '商品IDの形式が正しくありません: abc',
  },
  {
    failure: { kind: 'unknown_category', slug: 'sweets' },
    status: 400,
    message: '存在しないカテゴリです: sweets',
  },
  {
    failure: { kind: 'product_not_found', productId: 999 },
    status: 404,
    message: '商品が見つかりません: 999',
  },
];

for (const { failure, status, message } of failureCases) {
  checkJson(`本文8節: ${failure.kind} の HTTP 表現`, describeFailure(failure), { status, message });
}

// ---------------------------------------------------------------------------
// 問題2：ページ送りの計算（1ページの件数を変えた場合）
// ---------------------------------------------------------------------------
checkJson('問題2: 1ページ2件で5件の3ページ目', calcPagination(5, 3, 2), {
  page: 3,
  totalPages: 3,
  skip: 4,
  take: 2,
});
checkJson('問題2: 1ページ2件で範囲外', calcPagination(5, 10, 2), {
  page: 3,
  totalPages: 3,
  skip: 4,
  take: 2,
});
checkJson('問題2: 1ページ10件なら1ページだけ', calcPagination(5, 1, 10), {
  page: 1,
  totalPages: 1,
  skip: 0,
  take: 10,
});
checkJson('問題2: 0以下のページ番号は1に寄せる', calcPagination(5, 0, 2), {
  page: 1,
  totalPages: 3,
  skip: 0,
  take: 2,
});

// ---------------------------------------------------------------------------
// 問題4：在庫ありだけを表示する絞り込みを足す
// ---------------------------------------------------------------------------
type ProductQueryV2 = ProductQuery & { inStockOnly: boolean };

function parseInStockOnly(value: string | string[] | undefined): boolean {
  return firstValue(value) === 'true';
}

function parseProductQueryV2(raw: RawSearchParams): ProductQueryV2 {
  return {
    ...parseProductQuery(raw),
    inStockOnly: parseInStockOnly(raw['inStock']),
  };
}

function selectProducts(
  products: readonly ProductSummary[],
  query: ProductQueryV2,
  categoryId: number | null
): ProductSummary[] {
  const inStock = query.inStockOnly
    ? products.filter((product) => product.stock > 0)
    : [...products];

  return filterAndSortProducts(inStock, categoryId, query.sort);
}

checkBoolean('問題4: inStock=true', parseProductQueryV2({ inStock: 'true' }).inStockOnly, true);
checkBoolean('問題4: inStock=false', parseProductQueryV2({ inStock: 'false' }).inStockOnly, false);
checkBoolean('問題4: inStock=1', parseProductQueryV2({ inStock: '1' }).inStockOnly, false);
checkBoolean('問題4: 指定なし', parseProductQueryV2({}).inStockOnly, false);
checkJson('問題4: 他の条件も一緒に解釈できる', parseProductQueryV2({ category: 'fabric', inStock: 'true' }), {
  categorySlug: 'fabric',
  sort: 'price-asc',
  page: 1,
  inStockOnly: true,
});

checkString(
  '問題4: 在庫ありだけ（全カテゴリ）',
  toIdList(selectProducts(PRODUCTS, parseProductQueryV2({ inStock: 'true' }), null)),
  '1,2,3,5'
);
checkString(
  '問題4: 在庫ありだけ（ファブリック）',
  toIdList(selectProducts(PRODUCTS, parseProductQueryV2({ inStock: 'true' }), 3)),
  '5'
);
checkString(
  '問題4: 在庫切れも含める（ファブリック）',
  toIdList(selectProducts(PRODUCTS, parseProductQueryV2({}), 3)),
  '4,5'
);

// ---------------------------------------------------------------------------
// 問題6：カテゴリごとの商品を返す JSON API
// ---------------------------------------------------------------------------
type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

type CategoryApiFailure =
  | { kind: 'category_not_found'; slug: string }
  | { kind: 'invalid_limit'; raw: string };

const DEFAULT_LIMIT = 5;

function parseLimit(raw: string | null): Result<number, CategoryApiFailure> {
  if (raw === null) {
    return { kind: 'ok', value: DEFAULT_LIMIT };
  }

  const limit = Number(raw);

  if (!Number.isInteger(limit) || limit < 1 || limit > 20) {
    return { kind: 'error', error: { kind: 'invalid_limit', raw } };
  }

  return { kind: 'ok', value: limit };
}

function describeCategoryFailure(failure: CategoryApiFailure): {
  status: number;
  message: string;
} {
  switch (failure.kind) {
    case 'category_not_found':
      return { status: 404, message: `カテゴリが見つかりません: ${failure.slug}` };
    case 'invalid_limit':
      return {
        status: 400,
        message: `limit は1以上20以下の整数で指定してください: ${failure.raw}`,
      };
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

const limitCases: { raw: string | null; expected: string }[] = [
  { raw: null, expected: 'ok:5' },
  { raw: '1', expected: 'ok:1' },
  { raw: '20', expected: 'ok:20' },
  { raw: '0', expected: 'error' },
  { raw: '21', expected: 'error' },
  { raw: '2.5', expected: 'error' },
  { raw: 'abc', expected: 'error' },
  { raw: '', expected: 'error' },
];

for (const { raw, expected } of limitCases) {
  const result = parseLimit(raw);
  const actual = result.kind === 'ok' ? `ok:${result.value}` : 'error';

  checkString(`問題6: parseLimit(${JSON.stringify(raw)})`, actual, expected);
}

checkJson(
  '問題6: カテゴリなしは404',
  describeCategoryFailure({ kind: 'category_not_found', slug: 'sweets' }),
  { status: 404, message: 'カテゴリが見つかりません: sweets' }
);
checkJson('問題6: limit 不正は400', describeCategoryFailure({ kind: 'invalid_limit', raw: '0' }), {
  status: 400,
  message: 'limit は1以上20以下の整数で指定してください: 0',
});

// limit を適用した結果（ファブリックは2件なので limit 1 で1件になる）
const fabricProducts = filterAndSortProducts(PRODUCTS, 3, 'price-asc');

checkString('問題6: limit 1 を適用', toIdList(fabricProducts.slice(0, 1)), '4');
checkString('問題6: limit 5 を適用', toIdList(fabricProducts.slice(0, 5)), '4,5');

// ---------------------------------------------------------------------------
// 問題7：キーワード検索
// ---------------------------------------------------------------------------
const MAX_KEYWORD_LENGTH = 50;

function parseKeyword(value: string | string[] | undefined): string {
  return (firstValue(value) ?? '').trim().slice(0, MAX_KEYWORD_LENGTH);
}

function searchProducts(
  products: readonly ProductSummary[],
  keyword: string
): ProductSummary[] {
  if (keyword === '') {
    return [...products];
  }

  const lowered = keyword.toLowerCase();

  return products.filter((product) => product.name.toLowerCase().includes(lowered));
}

function buildSearchTitle(keyword: string, count: number): string {
  return keyword === '' ? '商品一覧' : `「${keyword}」の検索結果（${count}件）`;
}

checkString('問題7: 前後の空白を落とす', parseKeyword('  マグ  '), 'マグ');
checkString('問題7: 空文字のまま', parseKeyword(undefined), '');
checkString('問題7: 空白だけなら空文字', parseKeyword('   '), '');
checkString('問題7: 配列なら最初の値', parseKeyword(['マグ', 'ふきん']), 'マグ');
checkNumber('問題7: 長すぎる語は切り詰める', parseKeyword('あ'.repeat(80)).length, 50);

checkString('問題7: 「マグ」で検索', toIdList(searchProducts(PRODUCTS, 'マグ')), '3');
checkString('問題7: 「クリーム」で検索', toIdList(searchProducts(PRODUCTS, 'クリーム')), '2');
checkString('問題7: 「の」で検索', toIdList(searchProducts(PRODUCTS, 'の')), '1,4,5');
checkString('問題7: 空文字なら全件', toIdList(searchProducts(PRODUCTS, '')), '1,2,3,4,5');
checkString('問題7: 該当なし', toIdList(searchProducts(PRODUCTS, 'ソックス')), '');

checkString('問題7: 検索結果のタイトル', buildSearchTitle('マグ', 1), '「マグ」の検索結果（1件）');
checkString('問題7: 該当なしのタイトル', buildSearchTitle('ソックス', 0), '「ソックス」の検索結果（0件）');
checkString('問題7: 検索していないときのタイトル', buildSearchTitle('', 5), '商品一覧');

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session21: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session21: ok');
