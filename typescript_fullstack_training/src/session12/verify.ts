/**
 * セッション12「型の絞り込み」の検証スクリプト。
 *
 * 本文（040）と練習問題の解答（042）に載せたコードと同じロジックを実行し、
 * 章に書いた「期待される出力」と一致するかを確認する。
 * 1つでも一致しなければ非0で終了する。
 *
 * console.log を1行ずつ出す章のコードは、この検証では
 * 「出力行を \n でつないだ文字列」を返す関数として表現している。
 *
 * 章のファイルでは別ファイルに分かれている型（SearchState など）が
 * この1ファイルでは衝突するため、接頭辞を付けたり関数の中に閉じ込めている。
 * 型の中身は章のコードと同じ。
 *
 * 実行: docker compose exec ts npx tsx src/session12/verify.ts
 */

// ---------------------------------------------------------------------------
// 共通の定数（本書は金額を整数の円で扱う）
// ---------------------------------------------------------------------------
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 "${expected}" / 実際 "${actual}"`);
    failedCount += 1;
  }
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

// ---------------------------------------------------------------------------
// この章で使う共通の型とデータ（本文「この章で使う共通の型とデータ」と同じ）
// ---------------------------------------------------------------------------
type Product = {
  id: number;
  name: string;
  price: number;
  stock: number;
  categoryId: number;
};

type OrderStatus = 'pending' | 'paid' | 'shipped' | 'cancelled';

const products: Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

const bathBodyProducts = products.filter((product) => product.categoryId === 1);
const kitchenProducts = products.filter((product) => product.categoryId === 2);

/** 章のコードでは find + ガード節で書いている箇所を、検証用に短く書くための道具 */
function requireProduct(id: number): Product {
  const product = products.find((candidate) => candidate.id === id);
  if (product === undefined) {
    throw new Error(`検証データが壊れています: id=${id}`);
  }
  return product;
}

// ---------------------------------------------------------------------------
// 本文 1節：型の絞り込みとは何か（src/session12/narrowing-intro.ts）
// ---------------------------------------------------------------------------
function describeProduct(product: Product | undefined): string {
  if (product === undefined) {
    return '該当する商品がありません';
  }
  return `${product.name}：${product.price}円`;
}

checkString(
  '本文1節: find の結果を絞り込む',
  describeProduct(products.find((product) => product.id === 3)),
  'マグカップ：2350円'
);
checkString(
  '本文1節: 見つからない場合',
  describeProduct(products.find((product) => product.id === 99)),
  '該当する商品がありません'
);

// noUncheckedIndexedAccess のもとでのインデックスアクセス
function bodyFirstProductName(): string {
  const first = products[0];
  if (first !== undefined) {
    return first.name;
  }
  return '(商品なし)';
}

checkString('本文1節: インデックスアクセスの絞り込み', bodyFirstProductName(), 'ラベンダーの石けん');

// ---------------------------------------------------------------------------
// 本文 2節：typeof による絞り込み（src/session12/typeof-narrowing.ts）
// ---------------------------------------------------------------------------
function findProductByQuery(query: number | string): Product | undefined {
  if (typeof query === 'number') {
    return products.find((product) => product.id === query);
  }
  return products.find((product) => product.name.includes(query));
}

function describeQueryResult(query: number | string): string {
  const product = findProductByQuery(query);
  if (product === undefined) {
    return `${query}：該当する商品がありません`;
  }
  return `${query}：${product.name}（${product.price}円）`;
}

checkString('本文2節: 数値で検索', describeQueryResult(3), '3：マグカップ（2350円）');
checkString(
  '本文2節: 文字列で検索',
  describeQueryResult('クリーム'),
  'クリーム：ハンドクリーム（1800円）'
);
checkString(
  '本文2節: 該当なし',
  describeQueryResult('コーヒー'),
  'コーヒー：該当する商品がありません'
);

function formatNote(note: string | null): string {
  if (note === null) {
    return '(メモなし)';
  }
  return `メモ：${note}`;
}

checkString('本文2節: メモあり', formatNote('ギフト包装希望'), 'メモ：ギフト包装希望');
checkString('本文2節: メモなし', formatNote(null), '(メモなし)');

// typeof が返す文字列（本文の表の裏付け）
checkString('本文2節: typeof null', typeof null, 'object');
checkString('本文2節: typeof 配列', typeof [], 'object');
checkString('本文2節: typeof オブジェクト', typeof { id: 1 }, 'object');
checkString('本文2節: typeof 関数', typeof formatNote, 'function');
checkString('本文2節: typeof 文字列', typeof '石けん', 'string');
checkString('本文2節: typeof 数値', typeof 480, 'number');

// ---------------------------------------------------------------------------
// 本文 3節：truthiness の落とし穴（bad-truthy.ts / good-truthy.ts）
// ---------------------------------------------------------------------------
function formatDiscountBad(percent: number | undefined): string {
  if (!percent) {
    return '割引の設定がありません';
  }
  return `${percent}%オフ`;
}

function formatDiscount(percent: number | undefined): string {
  if (percent === undefined) {
    return '割引の設定がありません';
  }
  return `${percent}%オフ`;
}

function bodyTruthyComparison(): string {
  return [
    `[Bad] 10 → ${formatDiscountBad(10)}`,
    `[Bad] 0 → ${formatDiscountBad(0)}`,
    `[Bad] undefined → ${formatDiscountBad(undefined)}`,
    `[Good] 10 → ${formatDiscount(10)}`,
    `[Good] 0 → ${formatDiscount(0)}`,
    `[Good] undefined → ${formatDiscount(undefined)}`,
  ].join('\n');
}

checkString(
  '本文3節 Bad/Good: 0 のときだけ結果が変わる',
  bodyTruthyComparison(),
  '[Bad] 10 → 10%オフ\n' +
    '[Bad] 0 → 割引の設定がありません\n' +
    '[Bad] undefined → 割引の設定がありません\n' +
    '[Good] 10 → 10%オフ\n' +
    '[Good] 0 → 0%オフ\n' +
    '[Good] undefined → 割引の設定がありません'
);

function formatKeyword(keyword: string | undefined): string {
  if (keyword === undefined) {
    return '(キーワード未指定)';
  }
  if (keyword.trim() === '') {
    return '(キーワードが空です)';
  }
  return `検索：${keyword}`;
}

// 本文は「undefined → 空文字 の順で判定する」ことだけを述べ、実装は問題2に回している
checkString('問題2: キーワード未指定', formatKeyword(undefined), '(キーワード未指定)');
checkString('問題2: 空白だけ', formatKeyword('   '), '(キーワードが空です)');
checkString('問題2: キーワードあり', formatKeyword('石けん'), '検索：石けん');

// 表の裏付け（空配列は truthy）
checkBoolean('本文3節: 空配列は truthy', Boolean([]), true);
checkBoolean('本文3節: 0 は falsy', Boolean(0), false);
checkBoolean('本文3節: 空文字は falsy', Boolean(''), false);

// ---------------------------------------------------------------------------
// 本文 4節：判別可能なユニオン（bad-search-state.ts / search-state.ts）
// ---------------------------------------------------------------------------
type SearchStateBad = {
  isLoading: boolean;
  products?: Product[];
  errorMessage?: string;
};

// 本文では紙面の都合で型と「ありえない状態」だけを載せている。
// ここでは本文が述べている「表示関数がエラーを飲み込む」ことまで確認する。
function renderSearchStateBad(state: SearchStateBad): string {
  if (state.isLoading) {
    return '検索中...';
  }
  if (state.errorMessage !== undefined) {
    return `エラー：${state.errorMessage}`;
  }
  if (state.products !== undefined) {
    return `${state.products.length}件見つかりました`;
  }
  return 'キーワードを入力してください';
}

checkString('本文4節 Bad: 読み込み中', renderSearchStateBad({ isLoading: true }), '検索中...');
checkString(
  '本文4節 Bad: エラー',
  renderSearchStateBad({ isLoading: false, errorMessage: 'ネットワークに接続できませんでした' }),
  'エラー：ネットワークに接続できませんでした'
);
checkString(
  '本文4節 Bad: 成功',
  renderSearchStateBad({ isLoading: false, products: bathBodyProducts }),
  '2件見つかりました'
);
checkString(
  '本文4節 Bad: 未検索',
  renderSearchStateBad({ isLoading: false }),
  'キーワードを入力してください'
);
// ありえない組み合わせが作れてしまい、エラーが無視される（本文の impossible と同じ値）
checkString(
  '本文4節 Bad: ありえない状態でエラーが飲み込まれる',
  renderSearchStateBad({ isLoading: true, errorMessage: '接続できません', products: [] }),
  '検索中...'
);

// 本文の Good（この章の主役）
type SearchIdle = { kind: 'idle' };
type SearchLoading = { kind: 'loading' };
type SearchSuccess = { kind: 'success'; products: Product[] };
type SearchError = { kind: 'error'; message: string };
type SearchState = SearchIdle | SearchLoading | SearchSuccess | SearchError;

function renderSearchState(state: SearchState): string {
  switch (state.kind) {
    case 'idle':
      return 'キーワードを入力してください';
    case 'loading':
      return '検索中...';
    case 'success':
      return `${state.products.length}件見つかりました：${state.products
        .map((product) => product.name)
        .join(' / ')}`;
    case 'error':
      return `エラー：${state.message}`;
  }
}

function bodySearchStates(): string {
  return [
    renderSearchState({ kind: 'idle' }),
    renderSearchState({ kind: 'loading' }),
    renderSearchState({ kind: 'success', products: bathBodyProducts }),
    renderSearchState({ kind: 'error', message: 'ネットワークに接続できませんでした' }),
  ].join('\n');
}

checkString(
  '本文4節 Good: 4状態の表示',
  bodySearchStates(),
  'キーワードを入力してください\n' +
    '検索中...\n' +
    '2件見つかりました：ラベンダーの石けん / ハンドクリーム\n' +
    'エラー：ネットワークに接続できませんでした'
);

// ---------------------------------------------------------------------------
// 本文 5節：never による網羅性チェック（bad-exhaustive.ts / exhaustive.ts）
// ---------------------------------------------------------------------------
/** セッション3の版（引数が string なので default に落ちる） */
function describeOrderStatusLoose(status: string): string {
  switch (status) {
    case 'pending':
      return 'お支払いをお待ちしています';
    case 'paid':
      return 'お支払いを確認しました。発送準備中です';
    case 'shipped':
      return '発送済みです';
    case 'cancelled':
      return 'キャンセルされました';
    default:
      return '不明なステータスです';
  }
}

checkString(
  '本文5節 Bad: 未知のステータスが黙って通る',
  describeOrderStatusLoose('refunded'),
  '不明なステータスです'
);

function describeOrderStatus(status: OrderStatus): string {
  switch (status) {
    case 'pending':
      return 'お支払いをお待ちしています';
    case 'paid':
      return 'お支払いを確認しました。発送準備中です';
    case 'shipped':
      return '発送済みです';
    case 'cancelled':
      return 'キャンセルされました';
    default: {
      const _exhaustive: never = status;
      throw new Error(`未知の注文ステータスです: ${String(_exhaustive)}`);
    }
  }
}

const allOrderStatuses: OrderStatus[] = ['pending', 'paid', 'shipped', 'cancelled'];

checkString(
  '本文5節 Good: 4状態の説明文',
  allOrderStatuses.map((status) => describeOrderStatus(status)).join('\n'),
  'お支払いをお待ちしています\n' +
    'お支払いを確認しました。発送準備中です\n' +
    '発送済みです\n' +
    'キャンセルされました'
);

/**
 * 「ステータスを追加したが switch を直していない」状態の実演。
 * never チェックを入れたままではコンパイルできないため、
 * ここでは実行時に何が起きるかだけを確認する。
 */
function describeOrderStatusAfterAdding(status: OrderStatus | 'refunded'): string {
  switch (status) {
    case 'pending':
      return 'お支払いをお待ちしています';
    case 'paid':
      return 'お支払いを確認しました。発送準備中です';
    case 'shipped':
      return '発送済みです';
    case 'cancelled':
      return 'キャンセルされました';
    default:
      throw new Error(`未知の注文ステータスです: ${String(status)}`);
  }
}

function bodyExhaustiveThrow(): string {
  try {
    return describeOrderStatusAfterAdding('refunded');
  } catch (error) {
    if (error instanceof Error) {
      return error.message;
    }
    return '想定外のエラー';
  }
}

checkString(
  '本文5節: 想定外の値は例外で止まる',
  bodyExhaustiveThrow(),
  '未知の注文ステータスです: refunded'
);

// ---------------------------------------------------------------------------
// 本文 6節：in 演算子（in-operator.ts / bad-in.ts / good-in.ts）
// 問題3でも同じ型・同じ関数を使う
// ---------------------------------------------------------------------------
type StorePickup = { storeId: number; storeName: string };
type HomeDelivery = { postalCode: string; address: string };
type ShippingTarget = StorePickup | HomeDelivery;

function formatShippingTarget(target: ShippingTarget): string {
  if ('storeId' in target) {
    return `店舗受け取り：${target.storeName}（店舗ID ${target.storeId}）`;
  }
  return `自宅配送：${target.postalCode} ${target.address}`;
}

checkString(
  '本文6節: in で店舗受け取りを判別',
  formatShippingTarget({ storeId: 7, storeName: '中央店' }),
  '店舗受け取り：中央店（店舗ID 7）'
);
checkString(
  '本文6節: in で自宅配送を判別',
  formatShippingTarget({ postalCode: '150-0001', address: '東京都渋谷区1-2-3' }),
  '自宅配送：150-0001 東京都渋谷区1-2-3'
);

// Bad：プロパティの組み合わせで判別する（動くが読みにくい）
function bodyBadInChain(): string {
  type StorePickupB = { storeId: number; storeName: string };
  type ConveniencePickupB = { storeId: number; chainName: string };
  type HomeDeliveryB = { postalCode: string; address: string };
  type ShippingTargetB = StorePickupB | ConveniencePickupB | HomeDeliveryB;

  const formatShippingTargetBad = (target: ShippingTargetB): string => {
    if ('storeId' in target && 'storeName' in target) {
      return `店舗受け取り：${target.storeName}`;
    }
    if ('storeId' in target && 'chainName' in target) {
      return `コンビニ受け取り：${target.chainName}`;
    }
    if ('postalCode' in target) {
      return `自宅配送：${target.postalCode}`;
    }
    return '不明な配送先';
  };

  return [
    formatShippingTargetBad({ storeId: 7, storeName: '中央店' }),
    formatShippingTargetBad({ storeId: 12, chainName: 'ミニマート' }),
    formatShippingTargetBad({ postalCode: '150-0001', address: '東京都渋谷区1-2-3' }),
  ].join('\n');
}

checkString(
  '本文6節 Bad: in の組み合わせ判別',
  bodyBadInChain(),
  '店舗受け取り：中央店\nコンビニ受け取り：ミニマート\n自宅配送：150-0001'
);

// Good：タグを付けて switch + never にする
function bodyTaggedShipping(): string {
  type StorePickupT = { kind: 'store'; storeId: number; storeName: string };
  type ConveniencePickupT = { kind: 'convenience'; storeId: number; chainName: string };
  type HomeDeliveryT = { kind: 'home'; postalCode: string; address: string };
  type ShippingTargetT = StorePickupT | ConveniencePickupT | HomeDeliveryT;

  const format = (target: ShippingTargetT): string => {
    switch (target.kind) {
      case 'store':
        return `店舗受け取り：${target.storeName}（店舗ID ${target.storeId}）`;
      case 'convenience':
        return `コンビニ受け取り：${target.chainName}（店舗ID ${target.storeId}）`;
      case 'home':
        return `自宅配送：${target.postalCode} ${target.address}`;
      default: {
        const _exhaustive: never = target;
        throw new Error(`未知の配送先です: ${JSON.stringify(_exhaustive)}`);
      }
    }
  };

  return [
    format({ kind: 'store', storeId: 7, storeName: '中央店' }),
    format({ kind: 'convenience', storeId: 12, chainName: 'ミニマート' }),
    format({ kind: 'home', postalCode: '150-0001', address: '東京都渋谷区1-2-3' }),
  ].join('\n');
}

checkString(
  '本文6節 Good: タグ付きの配送先',
  bodyTaggedShipping(),
  '店舗受け取り：中央店（店舗ID 7）\n' +
    'コンビニ受け取り：ミニマート（店舗ID 12）\n' +
    '自宅配送：150-0001 東京都渋谷区1-2-3'
);

// in はキーの存在を見る（値が undefined でも true）
const noteHolder: { note?: string } = { note: undefined };
checkBoolean('本文6節: in はキーの存在を見る', 'note' in noteHolder, true);
checkBoolean('本文6節: キーが無ければ false', 'memo' in noteHolder, false);

// ---------------------------------------------------------------------------
// 本文 7節：instanceof と Array.isArray（instanceof-narrowing.ts）
// 問題3でも同じ関数を使う
// ---------------------------------------------------------------------------
function formatOrderedAt(orderedAt: Date | string): string {
  if (orderedAt instanceof Date) {
    return orderedAt.toISOString().slice(0, 10);
  }
  return orderedAt.slice(0, 10);
}

checkString(
  '本文7節: Date を絞り込む',
  formatOrderedAt(new Date('2026-08-27T09:30:00Z')),
  '2026-08-27'
);
checkString('本文7節: 文字列を絞り込む', formatOrderedAt('2026-08-27 09:30'), '2026-08-27');

function formatTargets(target: Product | Product[]): string {
  if (Array.isArray(target)) {
    return `${target.length}件：${target.map((product) => product.name).join(' / ')}`;
  }
  return `1件：${target.name}`;
}

checkString('本文7節: 単体を渡す', formatTargets(requireProduct(3)), '1件：マグカップ');
checkString(
  '本文7節: 配列を渡す',
  formatTargets(bathBodyProducts),
  '2件：ラベンダーの石けん / ハンドクリーム'
);

// ---------------------------------------------------------------------------
// 本文 8節：ユーザー定義型ガード（type-guard.ts / lying-guard.ts）
// ---------------------------------------------------------------------------
/** boolean を返すだけの関数（絞り込みには使えない） */
function hasProducts(state: SearchState): boolean {
  return state.kind === 'success';
}

checkBoolean(
  '本文8節: boolean 版は判定自体は正しい',
  hasProducts({ kind: 'success', products: bathBodyProducts }),
  true
);
checkBoolean('本文8節: boolean 版（loading）', hasProducts({ kind: 'loading' }), false);

/** ユーザー定義型ガード */
function isSearchSuccess(state: SearchState): state is SearchSuccess {
  return state.kind === 'success';
}

// 本文8節：型ガードを通した if の中では products に触れる
function bodyGuardedCount(): string {
  const successState: SearchState = { kind: 'success', products };
  if (isSearchSuccess(successState)) {
    return `${successState.products.length}件見つかりました`;
  }
  return '(成功していない)';
}

checkString('本文8節: 型ガードで絞り込む', bodyGuardedCount(), '5件見つかりました');

/** 型ガードを filter に渡すと配列の型が変わる（問題6でも同じ形を使う） */
function summarizeStates(states: SearchState[]): string {
  const successStates = states.filter(isSearchSuccess);
  const total = successStates.reduce((sum, state) => sum + state.products.length, 0);
  return `成功${successStates.length}件 / 合計${total}件の商品`;
}

const bodyStates: SearchState[] = [
  { kind: 'idle' },
  { kind: 'success', products: bathBodyProducts },
  { kind: 'error', message: 'ネットワークに接続できませんでした' },
  { kind: 'success', products: kitchenProducts },
];

checkString(
  '本文8節: 型ガードで成功状態だけを集める',
  summarizeStates(bodyStates),
  '成功2件 / 合計3件の商品'
);

function isProduct(value: Product | undefined): value is Product {
  return value !== undefined;
}

function bodyCollectProducts(): string {
  const requestedIds = [1, 99, 3];
  const maybeProducts = requestedIds.map((id) => products.find((product) => product.id === id));
  const foundProducts = maybeProducts.filter(isProduct);
  return `${foundProducts.length}件：${foundProducts.map((product) => product.name).join(' / ')}`;
}

checkString(
  '本文8節: undefined を落として Product[] にする',
  bodyCollectProducts(),
  '2件：ラベンダーの石けん / マグカップ'
);

/**
 * TypeScript 5.5 以降は、単純な条件式のコールバックなら型述語が推論される。
 * 下の行は Product[] として代入できることが型チェックで確認される
 * （推論が働かなければ tsc --noEmit が失敗する）。
 */
function bodyInferredPredicate(): number {
  const requestedIds = [1, 99, 3];
  const maybeProducts = requestedIds.map((id) => products.find((product) => product.id === id));
  const inferred: Product[] = maybeProducts.filter((value) => value !== undefined);
  return inferred.length;
}

checkNumber('本文8節: 推論された型述語', bodyInferredPredicate(), 2);

/** 嘘をつく型ガード（型は通るが実行時に落ちる） */
function isSearchSuccessWrong(state: SearchState): state is SearchSuccess {
  return state.kind !== 'idle';
}

function countProductsWrong(state: SearchState): number {
  if (isSearchSuccessWrong(state)) {
    return state.products.length;
  }
  return 0;
}

checkNumber(
  '本文8節: 成功状態なら正しく動いてしまう',
  countProductsWrong({ kind: 'success', products }),
  5
);

function bodyLyingGuardMessage(): string {
  try {
    countProductsWrong({ kind: 'loading' });
    return '(エラーが起きなかった)';
  } catch (error) {
    if (error instanceof TypeError) {
      return error.message;
    }
    return '想定外のエラー';
  }
}

checkString(
  '本文8節: 嘘をつく型ガードは実行時に落ちる',
  bodyLyingGuardMessage(),
  "Cannot read properties of undefined (reading 'length')"
);

// ---------------------------------------------------------------------------
// 本文 1節の注意点：let に再代入すると絞り込みが解ける
// ---------------------------------------------------------------------------
function pickKeyword(first: string | undefined, second: string | undefined): string {
  let keyword = first;
  if (keyword === undefined) {
    keyword = second;
  }
  return keyword ?? '(キーワード未指定)';
}

checkString('本文1節: 2つ目が使われる', pickKeyword(undefined, '石けん'), '石けん');
checkString('本文1節: どちらも未指定', pickKeyword(undefined, undefined), '(キーワード未指定)');

// ---------------------------------------------------------------------------
// 問題1：typeof で2種類の入力を受け取る
// ---------------------------------------------------------------------------
function solveQ1(): string {
  return [
    describeQueryResult(3),
    describeQueryResult(1),
    describeQueryResult('クリーム'),
    describeQueryResult('コーヒー'),
    formatNote('ギフト包装希望'),
    formatNote(null),
  ].join('\n');
}

checkString(
  '問題1: 出力6行',
  solveQ1(),
  '3：マグカップ（2350円）\n' +
    '1：ラベンダーの石けん（480円）\n' +
    'クリーム：ハンドクリーム（1800円）\n' +
    'コーヒー：該当する商品がありません\n' +
    'メモ：ギフト包装希望\n' +
    '(メモなし)'
);

// 問題1 別解：文字列を先に判定しても結果は同じ
function findProductByQueryAlt(query: number | string): Product | undefined {
  if (typeof query === 'string') {
    return products.find((product) => product.name.includes(query));
  }
  return products.find((product) => product.id === query);
}

checkString(
  '問題1 別解: 判定順序を入れ替える',
  describeProduct(findProductByQueryAlt('クリーム')),
  'ハンドクリーム：1800円'
);
checkString(
  '問題1 別解: 数値でも同じ',
  describeProduct(findProductByQueryAlt(3)),
  'マグカップ：2350円'
);

// ---------------------------------------------------------------------------
// 問題2：truthiness の落とし穴
// ---------------------------------------------------------------------------
function solveQ2(): string {
  return [
    bodyTruthyComparison(),
    formatKeyword(undefined),
    formatKeyword('   '),
    formatKeyword('石けん'),
  ].join('\n');
}

checkString(
  '問題2: 出力9行',
  solveQ2(),
  '[Bad] 10 → 10%オフ\n' +
    '[Bad] 0 → 割引の設定がありません\n' +
    '[Bad] undefined → 割引の設定がありません\n' +
    '[Good] 10 → 10%オフ\n' +
    '[Good] 0 → 0%オフ\n' +
    '[Good] undefined → 割引の設定がありません\n' +
    '(キーワード未指定)\n' +
    '(キーワードが空です)\n' +
    '検索：石けん'
);

// 選択問題の裏付け：在庫0が登録済みかどうかの判定
function solveQ2Choice(stock: number | undefined): string {
  const byTruthy = stock ? '登録あり' : '登録なし'; // (A) 誤り
  const byUndefined = stock !== undefined ? '登録あり' : '登録なし'; // (B) 正解
  return `${byTruthy} / ${byUndefined}`;
}

checkString('問題2 選択問題: 在庫0の扱い', solveQ2Choice(0), '登録なし / 登録あり');
checkString('問題2 選択問題: 未登録の扱い', solveQ2Choice(undefined), '登録なし / 登録なし');
checkString('問題2 選択問題: 在庫ありの扱い', solveQ2Choice(12), '登録あり / 登録あり');

// ---------------------------------------------------------------------------
// 問題3：in と instanceof と Array.isArray
// ---------------------------------------------------------------------------
function solveQ3(): string {
  return [
    formatShippingTarget({ storeId: 7, storeName: '中央店' }),
    formatShippingTarget({ postalCode: '150-0001', address: '東京都渋谷区1-2-3' }),
    formatOrderedAt(new Date('2026-08-27T09:30:00Z')),
    formatOrderedAt('2026-08-27 09:30'),
    formatTargets(requireProduct(3)),
    formatTargets(products.filter((product) => product.categoryId === 1)),
  ].join('\n');
}

checkString(
  '問題3: 出力6行',
  solveQ3(),
  '店舗受け取り：中央店（店舗ID 7）\n' +
    '自宅配送：150-0001 東京都渋谷区1-2-3\n' +
    '2026-08-27\n' +
    '2026-08-27\n' +
    '1件：マグカップ\n' +
    '2件：ラベンダーの石けん / ハンドクリーム'
);

// ---------------------------------------------------------------------------
// 問題4・問題6で使う SearchState（本文の型に keyword を足したもの）
// 章のファイルでは SearchState という名前。この1ファイルでは本文の型と
// 衝突するため Q 接頭辞を付けている。
// ---------------------------------------------------------------------------
type QSearchIdle = { kind: 'idle' };
type QSearchLoading = { kind: 'loading'; keyword: string };
type QSearchSuccess = { kind: 'success'; keyword: string; products: Product[] };
type QSearchError = { kind: 'error'; message: string };
type QSearchState = QSearchIdle | QSearchLoading | QSearchSuccess | QSearchError;

const searchByName = (keyword: string): Product[] =>
  products.filter((product) => product.name.includes(keyword));

function renderQSearchState(state: QSearchState): string {
  switch (state.kind) {
    case 'idle':
      return 'キーワードを入力してください';

    case 'loading':
      return `「${state.keyword}」を検索中...`;

    case 'success': {
      if (state.products.length === 0) {
        return `「${state.keyword}」に一致する商品はありませんでした`;
      }
      const names = state.products.map((product) => product.name).join(' / ');
      return `「${state.keyword}」で${state.products.length}件見つかりました：${names}`;
    }

    case 'error':
      return `エラー：${state.message}`;

    default: {
      const _exhaustive: never = state;
      throw new Error(`未知の検索状態です: ${JSON.stringify(_exhaustive)}`);
    }
  }
}

function solveQ4(): string {
  return [
    renderQSearchState({ kind: 'idle' }),
    renderQSearchState({ kind: 'loading', keyword: '石けん' }),
    renderQSearchState({ kind: 'success', keyword: 'クリーム', products: searchByName('クリーム') }),
    renderQSearchState({ kind: 'success', keyword: 'コーヒー', products: searchByName('コーヒー') }),
    renderQSearchState({ kind: 'error', message: 'ネットワークに接続できませんでした' }),
  ].join('\n');
}

checkString(
  '問題4: 出力5行',
  solveQ4(),
  'キーワードを入力してください\n' +
    '「石けん」を検索中...\n' +
    '「クリーム」で1件見つかりました：ハンドクリーム\n' +
    '「コーヒー」に一致する商品はありませんでした\n' +
    'エラー：ネットワークに接続できませんでした'
);

// 問題4 別解：if の連鎖（成功時は件数だけを返す短い版）
function renderQSearchStateWithIf(state: QSearchState): string {
  if (state.kind === 'idle') {
    return 'キーワードを入力してください';
  }
  if (state.kind === 'loading') {
    return `「${state.keyword}」を検索中...`;
  }
  if (state.kind === 'success') {
    return state.products.length === 0
      ? `「${state.keyword}」に一致する商品はありませんでした`
      : `「${state.keyword}」で${state.products.length}件見つかりました`;
  }
  if (state.kind === 'error') {
    return `エラー：${state.message}`;
  }
  const _exhaustive: never = state;
  throw new Error(`未知の検索状態です: ${JSON.stringify(_exhaustive)}`);
}

checkString(
  '問題4 別解: if の連鎖でも同じ分岐になる',
  renderQSearchStateWithIf({
    kind: 'success',
    keyword: 'クリーム',
    products: searchByName('クリーム'),
  }),
  '「クリーム」で1件見つかりました'
);
checkString(
  '問題4 別解: 0件',
  renderQSearchStateWithIf({
    kind: 'success',
    keyword: 'コーヒー',
    products: searchByName('コーヒー'),
  }),
  '「コーヒー」に一致する商品はありませんでした'
);

// ---------------------------------------------------------------------------
// 問題5：注文ステータスを型で縛る
// ---------------------------------------------------------------------------
function canCancelOrder(status: OrderStatus): boolean {
  switch (status) {
    case 'pending':
    case 'paid':
      return true;
    case 'shipped':
    case 'cancelled':
      return false;
    default: {
      const _exhaustive: never = status;
      throw new Error(`未知の注文ステータスです: ${String(_exhaustive)}`);
    }
  }
}

function canTransitionTo(current: OrderStatus, next: OrderStatus): boolean {
  switch (current) {
    case 'pending':
      return next === 'paid' || next === 'cancelled';
    case 'paid':
      return next === 'shipped' || next === 'cancelled';
    case 'shipped':
    case 'cancelled':
      return false;
    default: {
      const _exhaustive: never = current;
      throw new Error(`未知の注文ステータスです: ${String(_exhaustive)}`);
    }
  }
}

function solveQ5(): string {
  const statuses: OrderStatus[] = ['pending', 'paid', 'shipped', 'cancelled'];

  const lines: string[] = [];
  for (const status of statuses) {
    const cancelLabel = canCancelOrder(status) ? 'キャンセル可能' : 'キャンセル不可';
    lines.push(`${status}：${describeOrderStatus(status)}（${cancelLabel}）`);
  }

  lines.push(`pending → paid: ${canTransitionTo('pending', 'paid')}`);
  lines.push(`paid → shipped: ${canTransitionTo('paid', 'shipped')}`);
  lines.push(`shipped → cancelled: ${canTransitionTo('shipped', 'cancelled')}`);
  lines.push(`paid → paid: ${canTransitionTo('paid', 'paid')}`);
  return lines.join('\n');
}

checkString(
  '問題5: 出力8行',
  solveQ5(),
  'pending：お支払いをお待ちしています（キャンセル可能）\n' +
    'paid：お支払いを確認しました。発送準備中です（キャンセル可能）\n' +
    'shipped：発送済みです（キャンセル不可）\n' +
    'cancelled：キャンセルされました（キャンセル不可）\n' +
    'pending → paid: true\n' +
    'paid → shipped: true\n' +
    'shipped → cancelled: false\n' +
    'paid → paid: false'
);

// 遷移ルールの網羅（セッション3で確定した表と同じ）
checkBoolean('問題5: pending → cancelled', canTransitionTo('pending', 'cancelled'), true);
checkBoolean('問題5: pending → shipped', canTransitionTo('pending', 'shipped'), false);
checkBoolean('問題5: paid → cancelled', canTransitionTo('paid', 'cancelled'), true);
checkBoolean('問題5: paid → pending', canTransitionTo('paid', 'pending'), false);
checkBoolean('問題5: cancelled → paid', canTransitionTo('cancelled', 'paid'), false);

// ---------------------------------------------------------------------------
// 問題6：ユーザー定義型ガードで「あるものだけ」を集める
// ---------------------------------------------------------------------------
type CartLine = { product: Product; quantity: number };

const cartItems = [
  { productId: 1, quantity: 2 },
  { productId: 99, quantity: 1 },
  { productId: 3, quantity: 1 },
];

function toCartLine(item: { productId: number; quantity: number }): CartLine | undefined {
  const product = products.find((candidate) => candidate.id === item.productId);
  if (product === undefined) {
    return undefined;
  }
  return { product, quantity: item.quantity };
}

function isCartLine(value: CartLine | undefined): value is CartLine {
  return value !== undefined;
}

function isQSearchSuccess(state: QSearchState): state is QSearchSuccess {
  return state.kind === 'success';
}

function solveQ6(): string {
  const cartLines = cartItems.map(toCartLine).filter(isCartLine);

  const missingIds = cartItems
    .filter((item) => toCartLine(item) === undefined)
    .map((item) => item.productId);

  const subtotal = cartLines.reduce(
    (total, line) => total + line.product.price * line.quantity,
    0
  );
  const tax = Math.floor(subtotal * TAX_RATE);
  const totalWithTax = subtotal + tax;
  const shippingFee = totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;
  const payableAmount = totalWithTax + shippingFee;

  const lineTexts = cartLines.map((line) => `${line.product.name} × ${line.quantity}`);

  const states: QSearchState[] = [
    { kind: 'idle' },
    { kind: 'success', keyword: 'クリーム', products: searchByName('クリーム') },
    { kind: 'error', message: 'ネットワークに接続できませんでした' },
    { kind: 'success', keyword: 'バッグ', products: searchByName('バッグ') },
  ];

  const successStates = states.filter(isQSearchSuccess);
  const totalProducts = successStates.reduce((sum, state) => sum + state.products.length, 0);

  return [
    `${cartLines.length}件：${lineTexts.join(' / ')}`,
    `見つからなかった商品ID: ${missingIds.join(' / ')}`,
    `小計${subtotal}円 / 消費税${tax}円 / 送料${shippingFee}円 / お支払い${payableAmount}円`,
    `成功${successStates.length}件 / 合計${totalProducts}件の商品`,
  ].join('\n');
}

checkString(
  '問題6: 出力4行',
  solveQ6(),
  '2件：ラベンダーの石けん × 2 / マグカップ × 1\n' +
    '見つからなかった商品ID: 99\n' +
    '小計3310円 / 消費税331円 / 送料0円 / お支払い3641円\n' +
    '成功2件 / 合計2件の商品'
);

// 支払総額の内訳（解答の表に書いた数値）
checkNumber('問題6: 小計', 480 * 2 + 2350 * 1, 3310);
checkNumber('問題6: 消費税', Math.floor(3310 * TAX_RATE), 331);
checkNumber('問題6: 税込商品合計', 3310 + 331, 3641);
checkNumber('問題6: 送料', 3641 >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE, 0);

// 問題6 別解1：map の結果を1度だけ作る
function solveQ6Alternative(): string {
  const maybeLines = cartItems.map(toCartLine);
  const cartLines = maybeLines.filter(isCartLine);
  const missingIds = cartItems
    .filter((item, index) => maybeLines[index] === undefined)
    .map((item) => item.productId);

  return `${cartLines.length}件 / 見つからなかった商品ID: ${missingIds.join(' / ')}`;
}

checkString(
  '問題6 別解1: map を1度だけ実行する',
  solveQ6Alternative(),
  '2件 / 見つからなかった商品ID: 99'
);

// 問題6 別解2：TypeScript 5.5 以降の推論に任せる
function solveQ6Inferred(): number {
  const cartLines: CartLine[] = cartItems.map(toCartLine).filter((line) => line !== undefined);
  return cartLines.length;
}

checkNumber('問題6 別解2: 推論された型述語', solveQ6Inferred(), 2);

// 問題6 の嘘をつく型ガード（q6-lying-guard.ts）
function countQProductsWrong(state: QSearchState): number {
  const isWrong = (target: QSearchState): target is QSearchSuccess => target.kind !== 'idle';
  if (isWrong(state)) {
    return state.products.length;
  }
  return 0;
}

function solveQ6LyingGuard(): string {
  const first = countQProductsWrong({ kind: 'success', keyword: '全件', products });
  try {
    countQProductsWrong({ kind: 'loading', keyword: '石けん' });
    return `${first}\n(エラーが起きなかった)`;
  } catch (error) {
    if (error instanceof TypeError) {
      return `${first}\n${error.message}`;
    }
    return `${first}\n想定外のエラー`;
  }
}

checkString(
  '問題6: 嘘をつく型ガードの実行結果',
  solveQ6LyingGuard(),
  "5\nCannot read properties of undefined (reading 'length')"
);

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session12: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session12: ok');
