// セッション23「データベース設計とPrisma」の検証スクリプト。
//
// この章のデータベース処理は web フォルダ側にあり、src 側の package.json には
// @prisma/client が入っていないため、ここから Prisma を import することはできない。
// Prisma を使う部分（スキーマ・クエリ・トランザクション）の型は、
// verify-all.sh の最後に走る web の型チェック（cd web && npx tsc --noEmit）と
// next build が担保する。
//
// このファイルでは、データベースに触らずに確かめられるロジックだけを検証する。
// 対応する web 側の実装は lib フォルダの stock.ts と product-fields.ts、
// および prisma フォルダの seed.ts の集計部分。
//
// 実行: docker compose exec ts npx tsx src/session23/verify.ts

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

function checkJson(label: string, actual: unknown, expected: unknown): void {
  checkString(label, JSON.stringify(actual), JSON.stringify(expected));
}

// ---------------------------------------------------------------------------
// 検証用のデータ。prisma/seed.ts が投入する内容と同じ。
// 集計と突き合わせに必要な列だけを持つ ProductRow で確かめる。
// ---------------------------------------------------------------------------
type CategoryRow = { id: number; name: string; slug: string };

type ProductRow = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryId: number;
};

const CATEGORIES: readonly CategoryRow[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const PRODUCTS: readonly ProductRow[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

// ---------------------------------------------------------------------------
// 本文8節：N+1 問題。発行される SELECT の本数を数えて比べる
// ---------------------------------------------------------------------------
type QueryLog = { selects: number };

function newLog(): QueryLog {
  return { selects: 0 };
}

/** 悪い例：商品を取ってから、商品1件ごとにカテゴリを引く（1 + N 本） */
function loadWithNPlusOne(
  products: readonly ProductRow[],
  categories: readonly CategoryRow[],
  log: QueryLog
): string[] {
  log.selects += 1; // 商品を取る1本

  return products.map((product) => {
    log.selects += 1; // 商品ごとに1本ずつ増える

    const category = categories.find((item) => item.id === product.categoryId);

    return `${product.name}=${category?.name ?? '未分類'}`;
  });
}

/** 良い例：関連するカテゴリを1本でまとめて引く（include が内部でしていること） */
function loadWithInclude(
  products: readonly ProductRow[],
  categories: readonly CategoryRow[],
  log: QueryLog
): string[] {
  log.selects += 1; // 商品を取る1本

  const wantedIds = new Set(products.map((product) => product.categoryId));

  log.selects += 1; // 必要なカテゴリを IN でまとめて取る1本

  const nameById = new Map<number, string>(
    categories
      .filter((category) => wantedIds.has(category.id))
      .map((category) => [category.id, category.name] as const)
  );

  return products.map(
    (product) => `${product.name}=${nameById.get(product.categoryId) ?? '未分類'}`
  );
}

/** 商品の件数から、発行される SELECT の本数を見積もる */
function projectSelectCount(strategy: 'n-plus-one' | 'include', productCount: number): number {
  return strategy === 'n-plus-one' ? productCount + 1 : 2;
}

const nPlusOneLog = newLog();
const includeLog = newLog();
const expectedLabels =
  'ラベンダーの石けん=バス・ボディケア, ハンドクリーム=バス・ボディケア, ' +
  'マグカップ=キッチン雑貨, リネンのふきん=ファブリック, コットンのトートバッグ=ファブリック';

checkString(
  '本文8節: N+1 でも結果は正しい',
  loadWithNPlusOne(PRODUCTS, CATEGORIES, nPlusOneLog).join(', '),
  expectedLabels
);
checkString(
  '本文8節: include でも同じ結果',
  loadWithInclude(PRODUCTS, CATEGORIES, includeLog).join(', '),
  expectedLabels
);
checkNumber('本文8節: N+1 の SELECT 本数（商品5件）', nPlusOneLog.selects, 6);
checkNumber('本文8節: include の SELECT 本数（商品5件）', includeLog.selects, 2);
checkNumber('本文8節: N+1 は件数に比例する（50件）', projectSelectCount('n-plus-one', 50), 51);
checkNumber('本文8節: include は件数によらず一定（50件）', projectSelectCount('include', 50), 2);
checkNumber('本文8節: 商品0件なら N+1 も1本', projectSelectCount('n-plus-one', 0), 1);

// ---------------------------------------------------------------------------
// 本文7節：select / include で「何を取るか」を決める（web の lib/product-fields.ts と同じ実装）
// ---------------------------------------------------------------------------
type ProductFieldSet = 'summary' | 'detail';

const SUMMARY_FIELDS = ['id', 'name', 'price', 'stock', 'imageUrl', 'categoryId'] as const;

const DETAIL_FIELDS = [
  'id',
  'name',
  'price',
  'stock',
  'description',
  'imageUrl',
  'categoryId',
] as const;

function parseFieldSet(raw: string | null): ProductFieldSet {
  return raw === 'detail' ? 'detail' : 'summary';
}

function describeFieldSet(set: ProductFieldSet): {
  fields: readonly string[];
  relations: readonly string[];
} {
  switch (set) {
    case 'summary':
      return { fields: SUMMARY_FIELDS, relations: [] };
    case 'detail':
      return { fields: DETAIL_FIELDS, relations: ['category'] };
    default: {
      const unreachable: never = set;

      throw new Error(`未知のフィールド指定です: ${String(unreachable)}`);
    }
  }
}

const fieldSetCases: { raw: string | null; expected: ProductFieldSet }[] = [
  { raw: null, expected: 'summary' },
  { raw: 'summary', expected: 'summary' },
  { raw: 'detail', expected: 'detail' },
  { raw: 'full', expected: 'summary' },
  { raw: '', expected: 'summary' },
];

for (const { raw, expected } of fieldSetCases) {
  checkString(`本文7節: parseFieldSet(${JSON.stringify(raw)})`, parseFieldSet(raw), expected);
}

checkString(
  '本文7節: 一覧で取る列',
  describeFieldSet('summary').fields.join(','),
  'id,name,price,stock,imageUrl,categoryId'
);
checkString('本文7節: 一覧では関連を取らない', describeFieldSet('summary').relations.join(','), '');
checkString(
  '本文7節: 詳細で取る列',
  describeFieldSet('detail').fields.join(','),
  'id,name,price,stock,description,imageUrl,categoryId'
);
checkString(
  '本文7節: 詳細ではカテゴリも取る',
  describeFieldSet('detail').relations.join(','),
  'category'
);

// ---------------------------------------------------------------------------
// 本文10節：在庫引当の判定（web の lib/stock.ts と同じ実装）
// ---------------------------------------------------------------------------
type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

const MAX_CART_QUANTITY = 10;

type StockFailure =
  | { kind: 'invalid_quantity'; quantity: number }
  | { kind: 'out_of_stock'; productId: number }
  | { kind: 'insufficient_stock'; productId: number; stock: number; quantity: number };

function judgeQuantity(quantity: number): Result<number, StockFailure> {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_CART_QUANTITY) {
    return { kind: 'error', error: { kind: 'invalid_quantity', quantity } };
  }

  return { kind: 'ok', value: quantity };
}

function judgeReservation(
  productId: number,
  stock: number,
  quantity: number
): Result<{ nextStock: number }, StockFailure> {
  const judged = judgeQuantity(quantity);

  if (judged.kind === 'error') {
    return { kind: 'error', error: judged.error };
  }

  if (stock <= 0) {
    return { kind: 'error', error: { kind: 'out_of_stock', productId } };
  }

  if (stock < quantity) {
    return { kind: 'error', error: { kind: 'insufficient_stock', productId, stock, quantity } };
  }

  return { kind: 'ok', value: { nextStock: stock - quantity } };
}

function describeStockFailure(failure: StockFailure): string {
  switch (failure.kind) {
    case 'invalid_quantity':
      return `数量は1以上${MAX_CART_QUANTITY}以下の整数で指定してください: ${failure.quantity}`;
    case 'out_of_stock':
      return `在庫切れです（商品ID ${failure.productId}）`;
    case 'insufficient_stock':
      return `在庫が足りません（商品ID ${failure.productId}：在庫 ${failure.stock} / 要求 ${failure.quantity}）`;
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/** 判定結果を短い文字列にして比較しやすくする */
function summarize(result: Result<{ nextStock: number }, StockFailure>): string {
  return result.kind === 'ok' ? `ok:${result.value.nextStock}` : `error:${result.error.kind}`;
}

const reservationCases: { stock: number; quantity: number; expected: string }[] = [
  { stock: 24, quantity: 1, expected: 'ok:23' },
  { stock: 3, quantity: 3, expected: 'ok:0' },
  { stock: 3, quantity: 4, expected: 'error:insufficient_stock' },
  { stock: 0, quantity: 1, expected: 'error:out_of_stock' },
  { stock: 5, quantity: 0, expected: 'error:invalid_quantity' },
  { stock: 5, quantity: -1, expected: 'error:invalid_quantity' },
  { stock: 5, quantity: 1.5, expected: 'error:invalid_quantity' },
  { stock: 24, quantity: 11, expected: 'error:invalid_quantity' },
  { stock: 24, quantity: 10, expected: 'ok:14' },
];

for (const { stock, quantity, expected } of reservationCases) {
  checkString(
    `本文10節: judgeReservation(在庫 ${stock}, 要求 ${quantity})`,
    summarize(judgeReservation(3, stock, quantity)),
    expected
  );
}

checkString(
  '本文10節: 在庫切れのメッセージ',
  describeStockFailure({ kind: 'out_of_stock', productId: 4 }),
  '在庫切れです（商品ID 4）'
);
checkString(
  '本文10節: 在庫不足のメッセージ',
  describeStockFailure({ kind: 'insufficient_stock', productId: 3, stock: 1, quantity: 2 }),
  '在庫が足りません（商品ID 3：在庫 1 / 要求 2）'
);
checkString(
  '本文10節: 数量が不正なときのメッセージ',
  describeStockFailure({ kind: 'invalid_quantity', quantity: 11 }),
  '数量は1以上10以下の整数で指定してください: 11'
);

// 在庫切れの商品（リネンのふきん）はマスタでも必ず引当に失敗する
const linenCloth = PRODUCTS.find((product) => product.id === 4);

checkString(
  '本文10節: リネンのふきんは在庫切れ',
  linenCloth === undefined
    ? 'not found'
    : summarize(judgeReservation(linenCloth.id, linenCloth.stock, 1)),
  'error:out_of_stock'
);

// ---------------------------------------------------------------------------
// 本文10節：条件付き更新の結果（updateMany の count）をどう読むか
// ---------------------------------------------------------------------------
type ReserveOutcome = 'reserved' | 'conflict';

function interpretUpdatedCount(count: number): ReserveOutcome {
  // where に stock の条件を入れているので、0件なら「他の誰かに先を越された or 在庫不足」
  return count === 1 ? 'reserved' : 'conflict';
}

checkString('本文10節: 1件更新できたら引当成功', interpretUpdatedCount(1), 'reserved');
checkString('本文10節: 0件なら引当失敗', interpretUpdatedCount(0), 'conflict');

// 同時に2人が「在庫3のマグカップを2点」引こうとしたときの流れ。
// 条件付き更新なら、先に更新できた1人だけが成功する。
const concurrent: number[] = [1, 0];

checkString(
  '本文10節: 同時実行では1人だけ成功する',
  concurrent.map((count) => interpretUpdatedCount(count)).join(','),
  'reserved,conflict'
);

// ---------------------------------------------------------------------------
// 本文5節：シードの検算（prisma/seed.ts の集計部分と同じ実装）
// ---------------------------------------------------------------------------
type StockValueRow = { name: string; stockValue: number };

function sumStockValueByCategory(
  products: readonly ProductRow[],
  categories: readonly CategoryRow[]
): StockValueRow[] {
  const nameById = new Map<number, string>(
    categories.map((category) => [category.id, category.name] as const)
  );
  const valueByName = new Map<string, number>();

  for (const product of products) {
    const name = nameById.get(product.categoryId) ?? '未分類';
    const current = valueByName.get(name) ?? 0;

    valueByName.set(name, current + product.price * product.stock);
  }

  return [...valueByName].map(([name, stockValue]) => ({ name, stockValue }));
}

const stockValues = sumStockValueByCategory(PRODUCTS, CATEGORIES);

checkJson('本文5節: カテゴリ別の在庫金額', stockValues, [
  { name: 'バス・ボディケア', stockValue: 33120 },
  { name: 'キッチン雑貨', stockValue: 7050 },
  { name: 'ファブリック', stockValue: 14000 },
]);
checkNumber(
  '本文5節: 在庫金額の合計',
  stockValues.reduce((sum, row) => sum + row.stockValue, 0),
  54170
);

// ---------------------------------------------------------------------------
// 本文1節：外部キーの整合。参照先が無い categoryId が1件でもあれば設計が破れている
// ---------------------------------------------------------------------------
function findOrphanCategoryIds(
  products: readonly ProductRow[],
  categories: readonly CategoryRow[]
): number[] {
  const knownIds = new Set(categories.map((category) => category.id));

  return [
    ...new Set(
      products
        .filter((product) => !knownIds.has(product.categoryId))
        .map((product) => product.categoryId)
    ),
  ];
}

checkJson('本文1節: マスタに孤児は無い', findOrphanCategoryIds(PRODUCTS, CATEGORIES), []);
checkJson(
  '本文1節: 存在しないカテゴリを指す行は検出できる',
  findOrphanCategoryIds(
    [...PRODUCTS, { id: 6, name: '未登録の商品', price: 100, stock: 1, categoryId: 99 }],
    CATEGORIES
  ),
  [99]
);
checkNumber('本文1節: カテゴリの slug は重複しない', new Set(CATEGORIES.map((c) => c.slug)).size, 3);
checkNumber('本文1節: 商品の主キーは重複しない', new Set(PRODUCTS.map((p) => p.id)).size, 5);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session23: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session23: ok');
