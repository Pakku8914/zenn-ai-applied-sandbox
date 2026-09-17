// 復習04「セッション20〜28の横断復習」の練習問題の解答を検証する。
// 章に載せた「期待される出力」と1文字でも違えばエラー終了する。
//
// 問題6のテストは vitest 側（review04.test.ts）でも走る。
// 実行: docker compose exec ts npx tsx src/review04/verify.ts

import { delayWithSignal } from '../session17/async-tools';
import { PRODUCTS, cartLine } from './shared';
import type { ProductRow, SessionUser } from './shared';
import { PRODUCTS_TAG, createTtlCache } from './toolbox';
import type { RateLimitState } from './toolbox';
import {
  SHOP_ROUTES,
  auditRelease,
  canRelease,
  changeCartQuantity,
  checkStepOrder,
  confirmOrder,
  countLinesWithSecret,
  createInMemoryShop,
  createMemoryLogger,
  createStubGateway,
  decideByAmount,
  describeJudgement,
  estimateSuiteMs,
  findMissingSteps,
  forceStaticAt,
  formatApiOutcome,
  formatCartOutcome,
  formatFailureLine,
  formatFindings,
  formatOrderOutcome,
  formatRouteRow,
  handleProductsRequest,
  judgeTestBalance,
  parseLogLevel,
  proposeRebalance,
  pushCookieReadDown,
  speedupRatio,
  summarizeFindings,
  summarizeReasons,
  summarizeRoutes,
  toApiFailure,
  toCartActionState,
  toCartApiResponse,
  toSeconds,
  totalTestCount,
} from './solutions';
import type {
  ApiRequest,
  CartStore,
  CheckoutFailure,
  ConfirmOrderDeps,
  ProductsApiDeps,
  ReleaseConfig,
  StepId,
  TestCounts,
} from './solutions';

/** 比較できる値 */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}`);
    console.error(`  期待値: ${String(expected)}`);
    console.error(`  実際　: ${String(actual)}`);
    process.exit(1);
  }
};

const REQUEST_ID = '11111111-2222-3333-4444-555555555555';
const TIMESTAMP = '2026-08-29T12:00:00.000Z';

const demoUser: SessionUser = {
  id: 1,
  email: 'demo@example.com',
  name: 'デモユーザー',
  role: 'user',
};

// 共通の前提を確認する
check('共通: マスタの値（マグカップ）', cartLine(3, 1).product.price, 2350);
check('共通: 在庫切れの商品が1件ある', PRODUCTS.filter((product) => product.stock === 0).length, 1);

// ---------------------------------------------------------------------------
// 問題1：失敗を HTTP のステータスコードに翻訳する（S18・S20・S12）
// ---------------------------------------------------------------------------
const q1Failures: readonly CheckoutFailure[] = [
  { kind: 'invalid_input', messages: ['数量：数量は1点以上にしてください'] },
  { kind: 'unauthenticated' },
  { kind: 'forbidden' },
  { kind: 'cart_item_not_found' },
  { kind: 'product_not_found', productId: 999 },
  { kind: 'out_of_stock', productId: 3, stock: 3, requested: 5 },
  { kind: 'payment_declined', reason: 'card_declined' },
  { kind: 'rate_limited', retryAfterSeconds: 60 },
  { kind: 'unexpected', internalMessage: "Prisma: Can't reach database server at db:5432" },
];

const q1Internal = JSON.stringify(
  toApiFailure({ kind: 'unexpected', internalMessage: 'db:5432 に接続できません' })
);

const q1Lines = [
  ...q1Failures.map((failure) => formatFailureLine(failure)),
  `内部メッセージが応答に含まれていない: ${!q1Internal.includes('db:5432')}`,
];

check(
  '問題1の出力',
  q1Lines.join('\n'),
  [
    '400 invalid_input / 数量：数量は1点以上にしてください',
    '401 unauthenticated / ログインしてください',
    '403 forbidden / この操作を行う権限がありません',
    '404 cart_item_not_found / 対象の明細が見つかりません',
    '404 product_not_found / 商品が見つかりません（商品ID 999）',
    '409 out_of_stock / 在庫が足りません（在庫 3点 / 希望 5点）',
    '422 payment_declined / 決済を完了できませんでした。カード情報をご確認ください',
    '429 rate_limited / リクエストが多すぎます（60秒後にお試しください）',
    '500 unexpected / サーバー側の問題で処理を完了できませんでした',
    '内部メッセージが応答に含まれていない: true',
  ].join('\n')
);

check(
  '問題1: 429 には Retry-After が付く',
  toApiFailure({ kind: 'rate_limited', retryAfterSeconds: 60 }).headers['Retry-After'] ?? '(なし)',
  '60'
);
check(
  '問題1: それ以外にヘッダは付けない',
  Object.keys(toApiFailure({ kind: 'forbidden' }).headers).length,
  0
);
check(
  '問題1: 通信の失敗は文言を変える',
  formatFailureLine({ kind: 'payment_declined', reason: 'network_error' }),
  '422 payment_declined / 決済サービスに接続できませんでした。しばらくしてからお試しください'
);

// ---------------------------------------------------------------------------
// 問題2：なぜ全ルートが動的になるのか（S27・S25・S21）
// ---------------------------------------------------------------------------
const q2PlanA = forceStaticAt(SHOP_ROUTES, '/about');
const q2PlanB = pushCookieReadDown(SHOP_ROUTES);

const q2Lines = [
  '=== 直す前 ===',
  summarizeRoutes(SHOP_ROUTES),
  `理由の内訳: ${summarizeReasons(SHOP_ROUTES)}`,
  "=== 案A: /about に dynamic = 'force-static' を付ける ===",
  summarizeRoutes(q2PlanA),
  '=== 案B: ヘッダの Cookie 読み取りを末端の部品に押し下げる ===',
  summarizeRoutes(q2PlanB),
  `理由の内訳: ${summarizeReasons(q2PlanB)}`,
];

check(
  '問題2の出力',
  q2Lines.join('\n'),
  [
    '=== 直す前 ===',
    '静的: （なし） / 動的: 5件',
    '理由の内訳: ルートレイアウトが cookies() を読んでいる ×5',
    "=== 案A: /about に dynamic = 'force-static' を付ける ===",
    '静的: /about / 動的: 4件',
    '=== 案B: ヘッダの Cookie 読み取りを末端の部品に押し下げる ===',
    '静的: /, /about / 動的: 3件',
    '理由の内訳: searchParams を読んでいる ×1, ページが cookies() を読んでいる ×2',
  ].join('\n')
);

// ルート1行の書式も確かめる（案Bのあと、/products は searchParams で動的のまま）
const q2Products = q2PlanB.find((route) => route.path === '/products');

check(
  '問題2: 1ルート分の表示',
  q2Products === undefined ? '(見つかりません)' : formatRouteRow(q2Products),
  '/products → Dynamic（searchParams を読んでいる）'
);

// ---------------------------------------------------------------------------
// 問題3：機密を漏らさない構造化ログ（S26・S27・S18）
// ---------------------------------------------------------------------------
const q3Logger = createMemoryLogger({
  requestId: REQUEST_ID,
  minLevel: 'info',
  timestamp: TIMESTAMP,
});

q3Logger.log('debug', 'ここは出ない（設定は info）', { note: 'debug の行' });
q3Logger.log('error', '決済に失敗しました: Bearer sk_live_abc.def-123 / カード 4242424242424242', {
  userId: 1,
  email: 'demo@example.com',
  password: 'lavender-2026',
  sessionId: '9f2c1d7b',
  cardNumber: '4242 4242 4242 4242',
  orderId: 'order-1001',
  level: 'debug',
  message: '差し替えようとしたメッセージ',
});

const q3Secrets = [
  'lavender-2026',
  '9f2c1d7b',
  '4242424242424242',
  'sk_live_abc',
  'demo@example.com',
  '差し替えようとした',
];

const q3Lines = [
  ...q3Logger.lines(),
  `出力された行数: ${q3Logger.lines().length}（debug の1行は出さない）`,
  `秘密が残っている行: ${countLinesWithSecret(q3Logger.lines(), q3Secrets)}行`,
  `LOG_LEVEL=verbose の解釈: ${parseLogLevel('verbose')}`,
];

check(
  '問題3の出力',
  q3Lines.join('\n'),
  [
    '{"level":"error","message":"決済に失敗しました: Bearer [REDACTED] / カード ************4242",' +
      `"requestId":"${REQUEST_ID}","timestamp":"${TIMESTAMP}",` +
      '"userId":1,"email":"d***@example.com","password":"[REDACTED]","sessionId":"[REDACTED]",' +
      '"cardNumber":"[REDACTED]","orderId":"order-1001"}',
    '出力された行数: 1（debug の1行は出さない）',
    '秘密が残っている行: 0行',
    'LOG_LEVEL=verbose の解釈: info',
  ].join('\n')
);

check('問題3: ログは1行（改行を含まない）', (q3Logger.lines()[0] ?? '').split('\n').length, 1);

// ---------------------------------------------------------------------------
// 問題4：3つの問題を抱えた Server Action を直す（S24・S25・S26・S18）
// ---------------------------------------------------------------------------
const q4Items = new Map<number, { userId: number; quantity: number }>([
  [1, { userId: 1, quantity: 1 }],
  [2, { userId: 2, quantity: 2 }],
]);

let q4Calls = 0;

const q4Store: CartStore = {
  updateQuantityForUser: async (cartItemId, userId, quantity) => {
    q4Calls += 1;

    const item = q4Items.get(cartItemId);

    // where: { id, userId } と同じ。持ち主が違えば0件
    if (item === undefined || item.userId !== userId) {
      return 0;
    }
    q4Items.set(cartItemId, { userId, quantity });

    return 1;
  },
};

const q4BrokenStore: CartStore = {
  updateQuantityForUser: async () => {
    q4Calls += 1;

    throw new Error("Prisma: Can't reach database server at db:5432");
  },
};

const q4Logger = createMemoryLogger({
  requestId: REQUEST_ID,
  minLevel: 'info',
  timestamp: TIMESTAMP,
});

const q4Cases: {
  label: string;
  user: SessionUser | undefined;
  store: CartStore;
  values: Record<string, unknown>;
}[] = [
  {
    label: '① 未ログイン',
    user: undefined,
    store: q4Store,
    values: { cartItemId: '1', quantity: '2' },
  },
  {
    label: '② 数量が0',
    user: demoUser,
    store: q4Store,
    values: { cartItemId: '1', quantity: '0' },
  },
  {
    label: '③ 数量が999',
    user: demoUser,
    store: q4Store,
    values: { cartItemId: '1', quantity: '999' },
  },
  {
    label: '④ 他人の明細',
    user: demoUser,
    store: q4Store,
    values: { cartItemId: '2', quantity: '2' },
  },
  {
    label: '⑤ 自分の明細',
    user: demoUser,
    store: q4Store,
    values: { cartItemId: '1', quantity: '2' },
  },
  {
    label: '⑥ データベースが落ちている',
    user: demoUser,
    store: q4BrokenStore,
    values: { cartItemId: '1', quantity: '2' },
  },
];

const q4Lines: string[] = [];
let q4LastMessage = '';

for (const testCase of q4Cases) {
  const result = await changeCartQuantity(
    { user: testCase.user, store: testCase.store, logger: q4Logger },
    testCase.values
  );

  q4LastMessage = formatCartOutcome(result);
  q4Lines.push(`${testCase.label} → ${q4LastMessage}`);
}

q4Lines.push(
  `データベースを呼んだ回数: ${q4Calls}（6件のうち3件は手前で弾いた）`,
  `例外の中身が応答に出ていない: ${!q4LastMessage.includes('db:5432')}`,
  `内部の詳細はログには残っている: ${countLinesWithSecret(q4Logger.lines(), ['db:5432']) === 1}`,
  `他人の明細の数量: ${q4Items.get(2)?.quantity ?? -1}点（変わっていない）`
);

check(
  '問題4の出力',
  q4Lines.join('\n'),
  [
    '① 未ログイン → 失敗 401 ログインしてください',
    '② 数量が0 → 失敗 400 数量：数量は1点以上にしてください',
    '③ 数量が999 → 失敗 400 数量：数量は10点以下にしてください',
    '④ 他人の明細 → 失敗 404 対象の明細が見つかりません',
    '⑤ 自分の明細 → 成功 数量を2点に変更しました',
    '⑥ データベースが落ちている → 失敗 500 サーバー側の問題で処理を完了できませんでした',
    'データベースを呼んだ回数: 3（6件のうち3件は手前で弾いた）',
    '例外の中身が応答に出ていない: true',
    '内部の詳細はログには残っている: true',
    '他人の明細の数量: 2点（変わっていない）',
  ].join('\n')
);

// 同じドメイン関数を2つの入口（Server Action とルートハンドラ）から使える
const q4Success = await changeCartQuantity(
  { user: demoUser, store: q4Store, logger: q4Logger },
  { cartItemId: '1', quantity: '3' }
);
const q4Failure = await changeCartQuantity(
  { user: demoUser, store: q4Store, logger: q4Logger },
  { cartItemId: '2', quantity: '3' }
);

check('問題4: 入口Aの状態（成功）', toCartActionState(q4Success).kind, 'ok');
check('問題4: 入口Aの状態（失敗）', toCartActionState(q4Failure).kind, 'error');
check('問題4: 入口Bのステータス（成功）', toCartApiResponse(q4Success).status, 200);
check('問題4: 入口Bのステータス（失敗）', toCartApiResponse(q4Failure).status, 404);

// ---------------------------------------------------------------------------
// 問題5：二重送信でも注文が1件しか作られないようにする（S20・S23・S24・S17）
// ---------------------------------------------------------------------------

// --- A: 同じ注文を2回同時に送る ---
const shopA = createInMemoryShop([
  [1, 24],
  [3, 3],
]);
const gatewayA = createStubGateway(decideByAmount);
const depsA: ConfirmOrderDeps = { db: shopA.db, gateway: gatewayA.gateway, user: demoUser };
const inputA = { orderId: 'order-1001', userId: 1, lines: [cartLine(3, 1), cartLine(1, 2)] };

const [firstA, secondA] = await Promise.all([
  confirmOrder(depsA, inputA),
  confirmOrder(depsA, inputA),
]);
const snapshotA = shopA.snapshot();

// --- B: 在庫3点の商品を2点ずつ、別の2人が同時に注文する ---
const otherUser: SessionUser = {
  id: 2,
  email: 'other@example.com',
  name: 'ほかの人',
  role: 'user',
};
const shopB = createInMemoryShop([[3, 3]]);
const gatewayB = createStubGateway(decideByAmount);

const [firstB, secondB] = await Promise.all([
  confirmOrder(
    { db: shopB.db, gateway: gatewayB.gateway, user: demoUser },
    { orderId: 'order-2001', userId: 1, lines: [cartLine(3, 2)] }
  ),
  confirmOrder(
    { db: shopB.db, gateway: gatewayB.gateway, user: otherUser },
    { orderId: 'order-2002', userId: 2, lines: [cartLine(3, 2)] }
  ),
]);
const snapshotB = shopB.snapshot();

// --- C: 決済が拒否されたら在庫を戻す ---
const shopC = createInMemoryShop([[3, 3]]);
const gatewayC = createStubGateway(() => ({ kind: 'failed', reason: 'card_declined' }));
const depsC: ConfirmOrderDeps = { db: shopC.db, gateway: gatewayC.gateway, user: demoUser };

const declined = await confirmOrder(depsC, {
  orderId: 'order-3001',
  userId: 1,
  lines: [cartLine(3, 1)],
});
const otherUsersOrder = await confirmOrder(depsC, {
  orderId: 'order-3002',
  userId: 2,
  lines: [cartLine(3, 1)],
});
const snapshotC = shopC.snapshot();

const q5Lines = [
  '=== A: 同じ注文を2回同時に送る ===',
  formatOrderOutcome('1回目', firstA),
  formatOrderOutcome('2回目', secondA),
  `作られた注文: ${snapshotA.orders.length}件 / 課金を試みた回数: ${gatewayA.chargeCount()}回`,
  `在庫: マグカップ ${snapshotA.stock.get(3) ?? -1}点 / ラベンダーの石けん ${snapshotA.stock.get(1) ?? -1}点`,
  '=== B: 在庫3点のマグカップを2点ずつ2人が注文する ===',
  formatOrderOutcome('Aさん', firstB),
  formatOrderOutcome('Bさん', secondB),
  `在庫: マグカップ ${snapshotB.stock.get(3) ?? -1}点 / 作られた注文: ${snapshotB.orders.length}件`,
  '=== C: 決済が拒否された場合 ===',
  formatOrderOutcome('結果', declined),
  `在庫: マグカップ ${snapshotC.stock.get(3) ?? -1}点（巻き戻った） / 作られた注文: ${snapshotC.orders.length}件`,
  formatOrderOutcome('他人の userId を指定', otherUsersOrder),
];

check(
  '問題5の出力',
  q5Lines.join('\n'),
  [
    '=== A: 同じ注文を2回同時に送る ===',
    '1回目: 成功 order-1001 / 支払総額 3641円 / 状態 paid',
    '2回目: 成功 order-1001 / 支払総額 3641円 / 状態 paid',
    '作られた注文: 1件 / 課金を試みた回数: 1回',
    '在庫: マグカップ 2点 / ラベンダーの石けん 22点',
    '=== B: 在庫3点のマグカップを2点ずつ2人が注文する ===',
    'Aさん: 成功 order-2001 / 支払総額 5170円 / 状態 paid',
    'Bさん: 失敗 409 在庫が足りません（在庫 1点 / 希望 2点）',
    '在庫: マグカップ 1点 / 作られた注文: 1件',
    '=== C: 決済が拒否された場合 ===',
    '結果: 失敗 422 決済を完了できませんでした。カード情報をご確認ください',
    '在庫: マグカップ 3点（巻き戻った） / 作られた注文: 0件',
    '他人の userId を指定: 失敗 403 この操作を行う権限がありません',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題6：テストの配分と CI の順序を診断する（S28・S19）
// ---------------------------------------------------------------------------
const CONE: TestCounts = { unit: 10, integration: 20, e2e: 70 };
const q6After = proposeRebalance(CONE);
const q6Steps: readonly StepId[] = [
  'checkout',
  'setup-node',
  'install',
  'build',
  'test',
  'lint',
  'typecheck',
];

const q6Lines = [
  `現状: ${describeJudgement(judgeTestBalance(CONE))} / ${toSeconds(estimateSuiteMs(CONE))}秒`,
  `提案: ${describeJudgement(judgeTestBalance(q6After))} / ${toSeconds(estimateSuiteMs(q6After))}秒`,
  `配分: ユニット ${q6After.unit} / 統合 ${q6After.integration} / E2E ${q6After.e2e}（合計 ${totalTestCount(q6After)}本）`,
  `同じ100本でも ${speedupRatio(CONE, q6After)}倍の差`,
  `CI の順序の問題: ${checkStepOrder(q6Steps).join(' / ')}`,
  `足りないステップ: ${findMissingSteps(q6Steps).length === 0 ? 'なし' : findMissingSteps(q6Steps).join(', ')}`,
];

check(
  '問題6の出力',
  q6Lines.join('\n'),
  [
    '現状: E2E が 70% です（アイスクリームコーン型） / 570.1秒',
    '提案: 健全です（ユニット 70%） / 90.7秒',
    '配分: ユニット 70 / 統合 20 / E2E 10（合計 100本）',
    '同じ100本でも 6.3倍の差',
    'CI の順序の問題: typecheck は test より前に置く / test は build より前に置く',
    '足りないステップ: なし',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題7：1本のリクエストを通す（S17〜S27 の合流）
// ---------------------------------------------------------------------------
const T0 = 1_800_000_000_000;

const q7Logger = createMemoryLogger({
  requestId: REQUEST_ID,
  minLevel: 'info',
  timestamp: TIMESTAMP,
});

type RequestOverrides = {
  method?: 'GET' | 'POST';
  query?: Record<string, string | undefined>;
  headers?: Record<string, string>;
};

const makeRequest = (overrides: RequestOverrides = {}): ApiRequest => ({
  method: overrides.method ?? 'GET',
  path: '/api/products',
  query: overrides.query ?? {},
  headers: overrides.headers ?? { 'x-forwarded-for': '203.0.113.10', host: 'localhost:3000' },
  user: undefined,
  now: T0,
});

let q7DbCalls = 0;

const q7Cache = createTtlCache<readonly ProductRow[]>(60_000);
const q7Deps: ProductsApiDeps = {
  rateLimitStore: new Map<string, RateLimitState>(),
  cache: q7Cache,
  logger: q7Logger,
  load: async (categoryId) => {
    q7DbCalls += 1;

    return PRODUCTS.filter((product) => categoryId === null || product.categoryId === categoryId);
  },
  timeoutMs: 100,
  retries: 1,
};

const q7Lines: string[] = ['=== キャッシュ ==='];

const first = await handleProductsRequest(q7Deps, makeRequest());

q7Lines.push(`${formatApiOutcome('① GET /api/products', first)}（DB ${q7DbCalls}回）`);

const second = await handleProductsRequest(q7Deps, makeRequest());

q7Lines.push(`${formatApiOutcome('② 同じ条件でもう一度', second)}（DB ${q7DbCalls}回）`);

const kitchen = await handleProductsRequest(q7Deps, makeRequest({ query: { category: 'kitchen' } }));

q7Lines.push(`${formatApiOutcome('③ ?category=kitchen', kitchen)}（DB ${q7DbCalls}回）`);

const broken = await handleProductsRequest(
  q7Deps,
  makeRequest({ query: { page: '0', sort: 'cheapest' } })
);

q7Lines.push(`${formatApiOutcome('④ ?page=0&sort=cheapest', broken)}（DB ${q7DbCalls}回）`);

q7Cache.invalidateTag(PRODUCTS_TAG);

const afterInvalidate = await handleProductsRequest(q7Deps, makeRequest());

q7Lines.push(
  `${formatApiOutcome('⑤ products タグを捨てたあと', afterInvalidate)}（DB ${q7DbCalls}回）`,
  '=== 守り ==='
);

const crossSite = await handleProductsRequest(
  q7Deps,
  makeRequest({
    method: 'POST',
    headers: {
      'x-forwarded-for': '203.0.113.10',
      host: 'localhost:3000',
      origin: 'https://evil.example',
    },
  })
);

q7Lines.push(formatApiOutcome('⑥ 別サイトからの POST', crossSite));

const q7LimitDeps: ProductsApiDeps = {
  ...q7Deps,
  rateLimitStore: new Map<string, RateLimitState>(),
};
let q7Blocked = '(まだ弾かれていない)';

for (let index = 0; index < 61; index += 1) {
  const outcome = await handleProductsRequest(q7LimitDeps, makeRequest());

  if (index === 60) {
    q7Blocked = formatApiOutcome('⑦ 61回目の GET', outcome);
  }
}

q7Lines.push(q7Blocked, '=== 非同期 ===');

let q7FlakyCalls = 0;
const q7FlakyDeps: ProductsApiDeps = {
  rateLimitStore: new Map<string, RateLimitState>(),
  cache: createTtlCache<readonly ProductRow[]>(60_000),
  logger: q7Logger,
  load: async () => {
    q7FlakyCalls += 1;

    if (q7FlakyCalls <= 2) {
      throw new Error('一時的にデータベースへ接続できません');
    }

    return PRODUCTS;
  },
  timeoutMs: 20,
  retries: 2,
};

const flaky = await handleProductsRequest(q7FlakyDeps, makeRequest());

q7Lines.push(`${formatApiOutcome('⑧ 2回失敗してから成功', flaky)}（試行 ${q7FlakyCalls}回）`);

let q7SlowCalls = 0;
const q7SlowDeps: ProductsApiDeps = {
  rateLimitStore: new Map<string, RateLimitState>(),
  cache: createTtlCache<readonly ProductRow[]>(60_000),
  logger: q7Logger,
  load: async (_categoryId, signal) => {
    q7SlowCalls += 1;
    await delayWithSignal(200, signal);

    return PRODUCTS;
  },
  timeoutMs: 20,
  retries: 2,
};

const slow = await handleProductsRequest(q7SlowDeps, makeRequest());

q7Lines.push(
  `${formatApiOutcome('⑨ 毎回タイムアウト', slow)}（試行 ${q7SlowCalls}回）`,
  `ログ: ${q7Logger.lines().length}行 / すべての行に requestId がある: ${q7Logger
    .lines()
    .every((logLine) => logLine.includes(REQUEST_ID))}`
);

check(
  '問題7の出力',
  q7Lines.join('\n'),
  [
    '=== キャッシュ ===',
    '① GET /api/products → 200 / 5件 / miss（DB 1回）',
    '② 同じ条件でもう一度 → 200 / 5件 / hit（DB 1回）',
    '③ ?category=kitchen → 200 / 1件 / miss（DB 2回）',
    '④ ?page=0&sort=cheapest → 200 / 5件 / hit（DB 2回）',
    '⑤ products タグを捨てたあと → 200 / 5件 / miss（DB 3回）',
    '=== 守り ===',
    '⑥ 別サイトからの POST → 403 この操作を行う権限がありません',
    '⑦ 61回目の GET → 429 リクエストが多すぎます（60秒後にお試しください）',
    '=== 非同期 ===',
    '⑧ 2回失敗してから成功 → 200 / 5件 / miss（試行 3回）',
    '⑨ 毎回タイムアウト → 500 サーバー側の問題で処理を完了できませんでした（試行 3回）',
    'ログ: 69行 / すべての行に requestId がある: true',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題8：リリース前の監査（S25・S26・S27・S28）
// ---------------------------------------------------------------------------
const SAFE_DOCKERFILE = [
  'FROM node:24-bookworm-slim AS deps',
  'RUN npm ci',
  'FROM node:24-bookworm-slim AS builder',
  'RUN npx next build',
  'FROM node:24-bookworm-slim AS runner',
  'COPY --from=builder /app/.next/standalone ./',
  'USER node',
  'CMD ["node", "server.js"]',
].join('\n');

const SAFE_HEADERS: Record<string, string> = {
  'Content-Security-Policy': "default-src 'self'; script-src 'self' 'nonce-abc' 'strict-dynamic'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Frame-Options': 'DENY',
  'Strict-Transport-Security': 'max-age=63072000; includeSubDomains',
};

const riskyRelease: ReleaseConfig = {
  setCookie: 'shop_session=abc; Path=/; Max-Age=28800; SameSite=Lax',
  securityHeaders: {
    ...SAFE_HEADERS,
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'",
  },
  envNames: [
    'DATABASE_URL',
    'SESSION_SECRET',
    'NEXT_PUBLIC_SITE_NAME',
    'NEXT_PUBLIC_API_TOKEN',
  ],
  ciSteps: ['checkout', 'setup-node', 'install', 'build', 'test', 'lint', 'typecheck'],
  pendingMigrations: ['20260901093000_add_order_items'],
  migrateCommand: 'migrate dev',
  dockerfile: SAFE_DOCKERFILE.replace('USER node\n', ''),
  testCounts: CONE,
};

const safeRelease: ReleaseConfig = {
  setCookie: 'shop_session=abc; Path=/; Max-Age=28800; SameSite=Lax; HttpOnly; Secure',
  securityHeaders: SAFE_HEADERS,
  envNames: ['DATABASE_URL', 'SESSION_SECRET', 'NEXT_PUBLIC_SITE_NAME'],
  ciSteps: ['checkout', 'setup-node', 'install', 'typecheck', 'lint', 'test', 'build'],
  pendingMigrations: [],
  migrateCommand: 'migrate deploy',
  dockerfile: SAFE_DOCKERFILE,
  testCounts: q6After,
};

const riskyFindings = auditRelease(riskyRelease);
const safeFindings = auditRelease(safeRelease);

const q8Lines = [
  '=== 直す前 ===',
  ...formatFindings(riskyFindings),
  `判定: ${summarizeFindings(riskyFindings)}`,
  '=== 直したあと ===',
  `指摘: ${formatFindings(safeFindings).length === 0 ? 'なし' : formatFindings(safeFindings).join(' / ')}`,
  `判定: ${summarizeFindings(safeFindings)}`,
];

check(
  '問題8の出力',
  q8Lines.join('\n'),
  [
    '=== 直す前 ===',
    '[critical] cookie_attributes: Cookie に HttpOnly, Secure が付いていません',
    "[critical] csp_unsafe_inline: CSP に 'unsafe-inline' が入っています",
    '[critical] public_secret: ブラウザに埋まる秘密があります（NEXT_PUBLIC_API_TOKEN）',
    '[warning] ci_step_order: typecheck は test より前に置く / test は build より前に置く',
    '[critical] migrations_pending: 未適用のマイグレーションが1件あります（20260901093000_add_order_items）',
    '[critical] migrate_command: 本番では migrate deploy を使ってください',
    '[critical] docker_root: 実行段に USER node がありません（root で動きます）',
    '[warning] test_balance: E2E が 70% です（アイスクリームコーン型）',
    '判定: 出せない（critical 6件 / warning 2件）',
    '=== 直したあと ===',
    '指摘: なし',
    '判定: 出せる（critical 0件 / warning 0件）',
  ].join('\n')
);

check('問題8: critical が1つでもあれば出せない', canRelease(riskyFindings), false);
check('問題8: 直したあとは出せる', canRelease(safeFindings), true);

console.log('review04: ok');
