// 復習04「セッション20〜28の横断復習」の全問題の解答例。
//
// 8問分を1つのファイルにまとめている（問題ごとにファイルを分けても、中身が同じなら正解）。
// 出力の照合は verify.ts、問題6のテストは review04.test.ts が行う。

import { z } from 'zod';
import { isAbortLike, retryWithBackoff, withTimeout } from '../session17/async-tools';
import { toMessage } from '../session18/errors';
import {
  CATEGORY_SLUGS,
  MAX_CART_QUANTITY,
  SORT_KEYS,
  buildPaymentSummary,
  err,
  findCategoryIdBySlug,
  ok,
  tryCatchAsync,
} from './shared';
import type { CartLine, ProductRow, Result, SessionUser } from './shared';
import {
  API_RATE_LIMIT,
  PRODUCTS_TAG,
  REDACTED,
  categoryTag,
  decideRateLimit,
  isSensitiveKey,
  isTrustedOrigin,
  maskEmail,
  maskTextSecrets,
} from './toolbox';
import type { RateLimitState, TtlCache } from './toolbox';

// ===========================================================================
// 問題1：失敗を HTTP のステータスコードに翻訳する（S18・S20・S12）
// ===========================================================================

/** この層で起こりうる「予測できる失敗」の全部。判別タグは本書共通の kind */
export type CheckoutFailure =
  | { kind: 'invalid_input'; messages: readonly string[] }
  | { kind: 'unauthenticated' }
  | { kind: 'forbidden' }
  | { kind: 'cart_item_not_found' }
  | { kind: 'product_not_found'; productId: number }
  | { kind: 'out_of_stock'; productId: number; stock: number; requested: number }
  | { kind: 'payment_declined'; reason: 'card_declined' | 'insufficient_funds' | 'network_error' }
  | { kind: 'rate_limited'; retryAfterSeconds: number }
  | { kind: 'unexpected'; internalMessage: string };

/**
 * 失敗の種類 → ステータスコードの1枚の表。
 * Record で書くと、CheckoutFailure に kind を足したときにここが型エラーになり、
 * 「新しい失敗をどのコードで返すか」を決め忘れられなくなる。
 */
const STATUS_BY_FAILURE_KIND: Record<CheckoutFailure['kind'], number> = {
  invalid_input: 400, // 入力の形が違う（直せるのはクライアント）
  unauthenticated: 401, // 誰か分からない
  forbidden: 403, // 誰かは分かるが、その操作は許されない
  cart_item_not_found: 404, // 他人のものでも「無い」と答える
  product_not_found: 404,
  out_of_stock: 409, // 形は正しいが、いまの在庫と矛盾している
  payment_declined: 422, // 形も在庫も正しいが、業務上の理由で処理できない
  rate_limited: 429,
  unexpected: 500, // こちら側の問題
};

export function toHttpStatus(failure: CheckoutFailure): number {
  return STATUS_BY_FAILURE_KIND[failure.kind];
}

/** 利用者に見せる1文。内部の事情（例外の文面）は絶対に混ぜない */
export function describeFailure(failure: CheckoutFailure): string {
  switch (failure.kind) {
    case 'invalid_input':
      return failure.messages.join(' / ');
    case 'unauthenticated':
      return 'ログインしてください';
    case 'forbidden':
      return 'この操作を行う権限がありません';
    case 'cart_item_not_found':
      return '対象の明細が見つかりません';
    case 'product_not_found':
      return `商品が見つかりません（商品ID ${failure.productId}）`;
    case 'out_of_stock':
      return `在庫が足りません（在庫 ${failure.stock}点 / 希望 ${failure.requested}点）`;
    case 'payment_declined':
      return failure.reason === 'network_error'
        ? '決済サービスに接続できませんでした。しばらくしてからお試しください'
        : '決済を完了できませんでした。カード情報をご確認ください';
    case 'rate_limited':
      return `リクエストが多すぎます（${failure.retryAfterSeconds}秒後にお試しください）`;
    case 'unexpected':
      return 'サーバー側の問題で処理を完了できませんでした';
    default: {
      // kind を足して switch を直し忘れると、ここで型エラーになる
      const unreachable: never = failure;

      throw new Error(`未対応の失敗があります: ${JSON.stringify(unreachable)}`);
    }
  }
}

export type ApiErrorBody = { error: { kind: string; message: string } };

export type ApiFailureResponse = {
  status: number;
  headers: Record<string, string>;
  body: ApiErrorBody;
};

export function toApiFailure(failure: CheckoutFailure): ApiFailureResponse {
  const headers: Record<string, string> =
    failure.kind === 'rate_limited'
      ? { 'Retry-After': String(failure.retryAfterSeconds) }
      : {};

  return {
    status: toHttpStatus(failure),
    headers,
    body: { error: { kind: failure.kind, message: describeFailure(failure) } },
  };
}

export function formatFailureLine(failure: CheckoutFailure): string {
  const response = toApiFailure(failure);

  return `${response.status} ${response.body.error.kind} / ${response.body.error.message}`;
}

/**
 * 失敗の Result を作る小さな窓口。
 * 引数に型注釈があるので、渡したオブジェクトが CheckoutFailure として検査される
 * （err({ kind: 'unauthenticaded' }) のような綴り間違いがここで止まる）。
 */
export function fail(failure: CheckoutFailure): Result<never, CheckoutFailure> {
  return err(failure);
}

// ===========================================================================
// 問題2：なぜ全ルートが動的になるのか（S27・S25・S21）
// ===========================================================================

export type DynamicConfig = 'auto' | 'force-dynamic' | 'force-static';

export type RouteSignals = {
  path: string;
  readsCookiesInLayout: boolean;
  readsCookiesInPage: boolean;
  readsSearchParams: boolean;
  dynamicConfig: DynamicConfig;
};

export type RenderingDecision = { kind: 'static' } | { kind: 'dynamic'; reason: string };

export function decideRendering(signals: RouteSignals): RenderingDecision {
  // force-static は他のすべてに勝つ。代わりに cookies() は空の値を返すようになる
  if (signals.dynamicConfig === 'force-static') {
    return { kind: 'static' };
  }
  if (signals.dynamicConfig === 'force-dynamic') {
    return { kind: 'dynamic', reason: "dynamic = 'force-dynamic' の指定" };
  }
  // レイアウトは配下のすべてのページに効く。ここが原因なら全ルートが動的になる
  if (signals.readsCookiesInLayout) {
    return { kind: 'dynamic', reason: 'ルートレイアウトが cookies() を読んでいる' };
  }
  if (signals.readsCookiesInPage) {
    return { kind: 'dynamic', reason: 'ページが cookies() を読んでいる' };
  }
  if (signals.readsSearchParams) {
    return { kind: 'dynamic', reason: 'searchParams を読んでいる' };
  }

  return { kind: 'static' };
}

export function formatRouteRow(signals: RouteSignals): string {
  const decision = decideRendering(signals);

  return decision.kind === 'static'
    ? `${signals.path} → Static`
    : `${signals.path} → Dynamic（${decision.reason}）`;
}

export function countDynamicRoutes(routes: readonly RouteSignals[]): number {
  return routes.filter((route) => decideRendering(route).kind === 'dynamic').length;
}

export function listStaticRoutes(routes: readonly RouteSignals[]): string {
  const paths = routes
    .filter((route) => decideRendering(route).kind === 'static')
    .map((route) => route.path);

  return paths.length === 0 ? '（なし）' : paths.join(', ');
}

export function summarizeRoutes(routes: readonly RouteSignals[]): string {
  return `静的: ${listStaticRoutes(routes)} / 動的: ${countDynamicRoutes(routes)}件`;
}

/** 動的になった理由を数える。同じ理由が何ルートに効いているかが分かる */
export function summarizeReasons(routes: readonly RouteSignals[]): string {
  const counts = new Map<string, number>();

  for (const route of routes) {
    const decision = decideRendering(route);

    if (decision.kind === 'dynamic') {
      counts.set(decision.reason, (counts.get(decision.reason) ?? 0) + 1);
    }
  }

  return [...counts].map(([reason, count]) => `${reason} ×${count}`).join(', ');
}

/** 案A：そのルートだけ設定で静的に固定する */
export function forceStaticAt(routes: readonly RouteSignals[], path: string): RouteSignals[] {
  return routes.map(
    (route): RouteSignals =>
      route.path === path ? { ...route, dynamicConfig: 'force-static' } : route
  );
}

/** 案B：ヘッダの Cookie 読み取りを末端の部品に押し下げる（レイアウトが読まなくなる） */
export function pushCookieReadDown(routes: readonly RouteSignals[]): RouteSignals[] {
  return routes.map((route): RouteSignals => ({ ...route, readsCookiesInLayout: false }));
}

/** 直す前の状態。ルートレイアウトがログイン名の表示のために Cookie を読んでいる */
export const SHOP_ROUTES: readonly RouteSignals[] = [
  {
    path: '/',
    readsCookiesInLayout: true,
    readsCookiesInPage: false,
    readsSearchParams: false,
    dynamicConfig: 'auto',
  },
  {
    path: '/about',
    readsCookiesInLayout: true,
    readsCookiesInPage: false,
    readsSearchParams: false,
    dynamicConfig: 'auto',
  },
  {
    path: '/products',
    readsCookiesInLayout: true,
    readsCookiesInPage: false,
    readsSearchParams: true,
    dynamicConfig: 'auto',
  },
  {
    path: '/cart',
    readsCookiesInLayout: true,
    readsCookiesInPage: true,
    readsSearchParams: false,
    dynamicConfig: 'auto',
  },
  {
    path: '/orders',
    readsCookiesInLayout: true,
    readsCookiesInPage: true,
    readsSearchParams: false,
    dynamicConfig: 'auto',
  },
];

// ===========================================================================
// 問題3：機密を漏らさない構造化ログ（S26・S27・S18）
// ===========================================================================

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;

const LEVEL_SEVERITY: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

export function parseLogLevel(raw: string | undefined): LogLevel {
  return LOG_LEVELS.find((level) => level === raw) ?? 'info';
}

export function shouldLog(configured: LogLevel, level: LogLevel): boolean {
  return LEVEL_SEVERITY[level] >= LEVEL_SEVERITY[configured];
}

export type LogFields = Record<string, unknown>;

/** ログ1行の骨格。追加情報でこの4つを上書きさせない */
const RESERVED_LOG_KEYS = ['level', 'message', 'requestId', 'timestamp'] as const;

export function maskLogFields(fields: LogFields): LogFields {
  const masked: LogFields = {};

  for (const [key, value] of Object.entries(fields)) {
    if ((RESERVED_LOG_KEYS as readonly string[]).includes(key)) {
      continue;
    }
    // ① キーの名前で伏せる（passwordHash・sessionId・cardNumber などに部分一致する）
    if (isSensitiveKey(key)) {
      masked[key] = REDACTED;
      continue;
    }
    // ② メールアドレスは「消す」のではなく「削る」（問い合わせ対応で最低限追える形に）
    if (key.toLowerCase().includes('email')) {
      masked[key] = typeof value === 'string' ? maskEmail(value) : REDACTED;
      continue;
    }
    // ③ キーからは分からない秘密（文章に紛れたトークン・カード番号）を伏せる
    masked[key] = typeof value === 'string' ? maskTextSecrets(value) : value;
  }

  return masked;
}

export type LogEntry = {
  level: LogLevel;
  message: string;
  requestId: string;
  timestamp: string;
  fields?: LogFields;
};

export function buildLogLine(entry: LogEntry): string {
  return JSON.stringify({
    level: entry.level,
    // 例外のメッセージをそのまま渡されても、文章に紛れた秘密は伏せる
    message: maskTextSecrets(entry.message),
    requestId: entry.requestId,
    timestamp: entry.timestamp,
    ...maskLogFields(entry.fields ?? {}),
  });
}

export type Logger = {
  log: (level: LogLevel, message: string, fields?: LogFields) => void;
  lines: () => readonly string[];
};

export type LoggerOptions = { requestId: string; minLevel: LogLevel; timestamp: string };

/** 出力先をメモリにしたロガー。時刻とリクエストIDは引数で固定する（テストのため） */
export function createMemoryLogger(options: LoggerOptions): Logger {
  const written: string[] = [];

  return {
    log: (level, message, fields) => {
      if (!shouldLog(options.minLevel, level)) {
        return;
      }
      written.push(
        buildLogLine({
          level,
          message,
          requestId: options.requestId,
          timestamp: options.timestamp,
          fields,
        })
      );
    },
    lines: () => written,
  };
}

/** ログの中に秘密が残っていないかを数える（検査が漏れを見つけられることを確かめる） */
export function countLinesWithSecret(
  lines: readonly string[],
  secrets: readonly string[]
): number {
  return lines.filter((line) => secrets.some((secret) => line.includes(secret))).length;
}

// ===========================================================================
// 問題4：3つの問題を抱えた Server Action を直す（S24・S25・S26・S18）
// ===========================================================================

const CART_FIELD_LABELS: Record<string, string> = { cartItemId: '明細', quantity: '数量' };

export const cartQuantitySchema = z.object({
  cartItemId: z.coerce
    .number({ error: '対象の明細を選び直してください' })
    .int({ error: '対象の明細を選び直してください' })
    .positive({ error: '対象の明細を選び直してください' }),
  quantity: z.coerce
    .number({ error: '数量は数字で入力してください' })
    .int({ error: '数量は整数で入力してください' })
    .min(1, { error: '数量は1点以上にしてください' })
    .max(MAX_CART_QUANTITY, { error: `数量は${MAX_CART_QUANTITY}点以下にしてください` }),
});

export function toErrorMessages(error: z.ZodError, labels: Record<string, string>): string[] {
  return error.issues.map((issue) => {
    const key = issue.path.map((segment) => String(segment)).join('.');
    const label = labels[key];

    return label === undefined ? issue.message : `${label}：${issue.message}`;
  });
}

/** データベース側の窓口。where に userId を含めた更新しか用意しない */
export type CartStore = {
  /** 更新できた件数を返す（Prisma の updateMany の count と同じ） */
  updateQuantityForUser: (
    cartItemId: number,
    userId: number,
    quantity: number
  ) => Promise<number>;
};

export type CartActionDeps = {
  user: SessionUser | undefined;
  store: CartStore;
  logger: Logger;
};

/**
 * ドメイン層。入口（Server Action / ルートハンドラ）に依存しない形で結果を返す。
 * 検証 → 認証 → 認可を含めた更新 → 例外の封じ込め、の順に関門を置く。
 */
export async function changeCartQuantity(
  deps: CartActionDeps,
  values: Record<string, unknown>
): Promise<Result<string, CheckoutFailure>> {
  // 分割して受け取る。あとで使う user が undefined でないことを型に覚えさせるため
  const user = deps.user;

  if (user === undefined) {
    return failAndLog(deps.logger, { kind: 'unauthenticated' });
  }

  const parsed = cartQuantitySchema.safeParse(values);

  if (!parsed.success) {
    return failAndLog(deps.logger, {
      kind: 'invalid_input',
      messages: toErrorMessages(parsed.error, CART_FIELD_LABELS),
    });
  }

  const { cartItemId, quantity } = parsed.data;
  const updated = await tryCatchAsync(() =>
    deps.store.updateQuantityForUser(cartItemId, user.id, quantity)
  );

  if (updated.kind === 'error') {
    // 例外の中身はログにだけ残し、画面には出さない
    return failAndLog(deps.logger, {
      kind: 'unexpected',
      internalMessage: updated.error.message,
    });
  }
  if (updated.value === 0) {
    // 他人の明細でも、存在しない明細でも同じ応答にする（存在を教えない）
    return failAndLog(deps.logger, { kind: 'cart_item_not_found' });
  }

  return ok(`数量を${quantity}点に変更しました`);
}

function failAndLog(logger: Logger, failure: CheckoutFailure): Result<never, CheckoutFailure> {
  logger.log(toHttpStatus(failure) >= 500 ? 'error' : 'warn', 'カートの数量変更に失敗しました', {
    failureKind: failure.kind,
    detail: failure.kind === 'unexpected' ? failure.internalMessage : describeFailure(failure),
  });

  return err(failure);
}

export type CartActionState =
  | { kind: 'idle' }
  | { kind: 'ok'; message: string }
  | { kind: 'error'; messages: string[] };

/** 入口A：Server Action が useActionState に返す状態 */
export function toCartActionState(result: Result<string, CheckoutFailure>): CartActionState {
  return result.kind === 'ok'
    ? { kind: 'ok', message: result.value }
    : { kind: 'error', messages: [describeFailure(result.error)] };
}

/** 入口B：ルートハンドラが返す応答（同じドメイン関数を使い回す） */
export function toCartApiResponse(
  result: Result<string, CheckoutFailure>
): { status: number; body: unknown } {
  if (result.kind === 'ok') {
    return { status: 200, body: { message: result.value } };
  }
  const response = toApiFailure(result.error);

  return { status: response.status, body: response.body };
}

export function formatCartOutcome(result: Result<string, CheckoutFailure>): string {
  return result.kind === 'ok'
    ? `成功 ${result.value}`
    : `失敗 ${toHttpStatus(result.error)} ${describeFailure(result.error)}`;
}

// ===========================================================================
// 問題5：二重送信でも注文が1件しか作られないようにする（S20・S23・S24・S17）
// ===========================================================================

export type OrderStatus = 'pending' | 'paid' | 'shipped' | 'cancelled';

export type OrderRecord = {
  id: string;
  userId: number;
  status: OrderStatus;
  totalAmount: number;
  idempotencyKey: string;
};

export type PaymentResult =
  | { kind: 'succeeded'; paymentId: string }
  | { kind: 'failed'; reason: 'card_declined' | 'insufficient_funds' | 'network_error' }
  | { kind: 'pending'; paymentId: string };

export type ChargeInput = { idempotencyKey: string; amount: number; orderId: string };

export interface PaymentGateway {
  charge(input: ChargeInput): Promise<PaymentResult>;
}

/** 冪等キーは注文から決まる。送信のたびに作り直すと二重決済を止められない */
export function buildIdempotencyKey(orderId: string): string {
  return `charge-${orderId}`;
}

export type ShopDatabase = {
  /** 在庫を条件付きで減らす。減らせた件数（0 か 1）を返す */
  decrementStock: (productId: number, quantity: number) => Promise<number>;
  findStockById: (productId: number) => Promise<number | undefined>;
  findOrderByKey: (idempotencyKey: string) => Promise<OrderRecord | undefined>;
  /** 同じ冪等キーの注文が既にあれば例外を投げる（データベースのユニーク制約） */
  insertOrder: (order: OrderRecord) => Promise<OrderRecord>;
  /** 中で例外が起きたら、この関数の中の変更をすべて巻き戻す */
  transaction: <T>(work: () => Promise<T>) => Promise<T>;
};

/** 予測できる失敗を、トランザクションの外まで運ぶための例外 */
export class OrderFailureError extends Error {
  override readonly name = 'OrderFailureError';
  readonly failure: CheckoutFailure;

  constructor(failure: CheckoutFailure) {
    super(`注文を確定できません: ${failure.kind}`);
    this.failure = failure;
  }
}

/** ユニーク制約違反。Prisma なら P2002 のエラーがこれに当たる */
export class DuplicateKeyError extends Error {
  override readonly name = 'DuplicateKeyError';

  constructor(message: string) {
    super(message);
  }
}

export type ConfirmOrderInput = {
  orderId: string;
  userId: number;
  lines: readonly CartLine[];
};

export type ConfirmOrderDeps = {
  db: ShopDatabase;
  gateway: PaymentGateway;
  user: SessionUser | undefined;
};

export async function confirmOrder(
  deps: ConfirmOrderDeps,
  input: ConfirmOrderInput
): Promise<Result<OrderRecord, CheckoutFailure>> {
  const user = deps.user;

  if (user === undefined) {
    return fail({ kind: 'unauthenticated' });
  }
  if (user.id !== input.userId) {
    return fail({ kind: 'forbidden' });
  }

  const idempotencyKey = buildIdempotencyKey(input.orderId);
  const summary = buildPaymentSummary(input.lines);

  // すでに同じキーで作った注文があれば、それを返す（作り直さない）
  const known = await deps.db.findOrderByKey(idempotencyKey);

  if (known !== undefined) {
    return ok(known);
  }

  const outcome = await tryCatchAsync(() =>
    deps.db.transaction(async () => {
      // 在庫の引当は順序と原子性が要る処理なので、あえて1件ずつ待つ
      for (const line of input.lines) {
        const updated = await deps.db.decrementStock(line.product.id, line.quantity);

        if (updated === 0) {
          // return ではなく throw。return するとトランザクションが巻き戻らない
          throw new OrderFailureError(await explainStockFailure(deps.db, line));
        }
      }

      const payment = await deps.gateway.charge({
        idempotencyKey,
        amount: summary.payableAmount,
        orderId: input.orderId,
      });

      if (payment.kind === 'failed') {
        throw new OrderFailureError({ kind: 'payment_declined', reason: payment.reason });
      }

      return deps.db.insertOrder({
        id: input.orderId,
        userId: user.id,
        status: payment.kind === 'succeeded' ? 'paid' : 'pending',
        totalAmount: summary.payableAmount,
        idempotencyKey,
      });
    })
  );

  if (outcome.kind === 'ok') {
    return ok(outcome.value);
  }

  const thrown = outcome.error;

  if (thrown instanceof OrderFailureError) {
    return err(thrown.failure);
  }
  if (thrown instanceof DuplicateKeyError) {
    // 同時に2回届いた場合。最後の砦はデータベースのユニーク制約
    const existing = await deps.db.findOrderByKey(idempotencyKey);

    return existing === undefined
      ? fail({ kind: 'unexpected', internalMessage: thrown.message })
      : ok(existing);
  }

  return fail({ kind: 'unexpected', internalMessage: thrown.message });
}

/** 「0件しか更新できなかった」理由を、もう1本だけ問い合わせて確かめる */
async function explainStockFailure(db: ShopDatabase, line: CartLine): Promise<CheckoutFailure> {
  const stock = await db.findStockById(line.product.id);

  return stock === undefined
    ? { kind: 'product_not_found', productId: line.product.id }
    : { kind: 'out_of_stock', productId: line.product.id, stock, requested: line.quantity };
}

export function formatOrderOutcome(
  label: string,
  result: Result<OrderRecord, CheckoutFailure>
): string {
  return result.kind === 'ok'
    ? `${label}: 成功 ${result.value.id} / 支払総額 ${result.value.totalAmount}円 / 状態 ${result.value.status}`
    : `${label}: 失敗 ${toHttpStatus(result.error)} ${describeFailure(result.error)}`;
}

// --- 検証用のスタブ（決済ゲートウェイとメモリ上のデータベース） ---------------

/** セッション24 の決済スタブと同じ規則。金額の下2桁で結果が決まる */
export function decideByAmount(input: ChargeInput): PaymentResult {
  const lastTwoDigits = Math.abs(Math.trunc(input.amount)) % 100;
  const paymentId = `pay_${input.idempotencyKey}`;

  if (lastTwoDigits === 1) {
    return { kind: 'failed', reason: 'card_declined' };
  }
  if (lastTwoDigits === 2) {
    return { kind: 'pending', paymentId };
  }

  return { kind: 'succeeded', paymentId };
}

export function createStubGateway(decide: (input: ChargeInput) => PaymentResult): {
  gateway: PaymentGateway;
  chargeCount: () => number;
} {
  const remembered = new Map<string, PaymentResult>();
  let count = 0;

  return {
    gateway: {
      charge: async (input) => {
        // 同じ冪等キーの再送には、覚えておいた結果をそのまま返す
        const known = remembered.get(input.idempotencyKey);

        if (known !== undefined) {
          return known;
        }
        count += 1;

        const result = decide(input);

        remembered.set(input.idempotencyKey, result);

        return result;
      },
    },
    chargeCount: () => count,
  };
}

export type ShopSnapshot = { stock: ReadonlyMap<number, number>; orders: readonly OrderRecord[] };

/**
 * メモリ上の偽のデータベース。
 * トランザクションは1本ずつ直列に実行し（PostgreSQL の行ロックの代わり）、
 * 中で例外が起きたら開始時点の状態に巻き戻す。
 */
export function createInMemoryShop(initialStock: readonly (readonly [number, number])[]): {
  db: ShopDatabase;
  snapshot: () => ShopSnapshot;
} {
  let stock = new Map<number, number>(initialStock);
  let orders: readonly OrderRecord[] = [];
  let queue: Promise<void> = Promise.resolve();

  const db: ShopDatabase = {
    decrementStock: async (productId, quantity) => {
      const current = stock.get(productId);

      // where に stock の条件を入れた updateMany と同じ。足りなければ0件
      if (current === undefined || current < quantity) {
        return 0;
      }
      stock.set(productId, current - quantity);

      return 1;
    },
    findStockById: async (productId) => stock.get(productId),
    findOrderByKey: async (idempotencyKey) =>
      orders.find((order) => order.idempotencyKey === idempotencyKey),
    insertOrder: async (order) => {
      if (orders.some((existing) => existing.idempotencyKey === order.idempotencyKey)) {
        throw new DuplicateKeyError(
          `orders.idempotency_key が重複しています: ${order.idempotencyKey}`
        );
      }
      orders = [...orders, order];

      return order;
    },
    transaction: async (work) => {
      const previous = queue;
      let release = (): void => {};

      queue = new Promise<void>((resolve) => {
        release = () => {
          resolve();
        };
      });
      await previous;

      const stockAtStart = new Map(stock);
      const ordersAtStart = orders;

      try {
        return await work();
      } catch (error: unknown) {
        // ROLLBACK。この関数の中で変えたものをすべて戻す
        stock = stockAtStart;
        orders = ordersAtStart;
        throw error;
      } finally {
        release();
      }
    },
  };

  return { db, snapshot: () => ({ stock: new Map(stock), orders }) };
}

// ===========================================================================
// 問題6：テストの配分と CI の順序を診断する（S28・S19）
// ===========================================================================

export type TestCounts = { unit: number; integration: number; e2e: number };

export type BalanceJudgement =
  | { kind: 'empty' }
  | { kind: 'ice-cream-cone'; e2ePercent: number }
  | { kind: 'unit-too-few'; unitPercent: number }
  | { kind: 'healthy'; unitPercent: number };

const MIN_UNIT_PERCENT = 60;
const MAX_E2E_PERCENT = 10;
const MAX_INTEGRATION_PERCENT = 30;

/** 1本あたりの目安（桁の感覚をつかむための仮の値） */
const UNIT_MS = 10;
const INTEGRATION_MS = 500;
const E2E_MS = 8000;

export function totalTestCount(counts: TestCounts): number {
  return counts.unit + counts.integration + counts.e2e;
}

export function judgeTestBalance(counts: TestCounts): BalanceJudgement {
  const total = totalTestCount(counts);

  if (total === 0) {
    return { kind: 'empty' };
  }

  const unitPercent = Math.round((counts.unit / total) * 100);
  const e2ePercent = Math.round((counts.e2e / total) * 100);

  // 先に E2E の偏りを見る。ここが太っているのがアイスクリームコーン型
  if (e2ePercent > MAX_E2E_PERCENT) {
    return { kind: 'ice-cream-cone', e2ePercent };
  }
  if (unitPercent < MIN_UNIT_PERCENT) {
    return { kind: 'unit-too-few', unitPercent };
  }

  return { kind: 'healthy', unitPercent };
}

export function describeJudgement(judgement: BalanceJudgement): string {
  switch (judgement.kind) {
    case 'empty':
      return 'テストが1本もありません';
    case 'ice-cream-cone':
      return `E2E が ${judgement.e2ePercent}% です（アイスクリームコーン型）`;
    case 'unit-too-few':
      return `ユニットが ${judgement.unitPercent}% しかありません`;
    case 'healthy':
      return `健全です（ユニット ${judgement.unitPercent}%）`;
    default: {
      const unreachable: never = judgement;

      throw new Error(`未対応の判定です: ${JSON.stringify(unreachable)}`);
    }
  }
}

export function estimateSuiteMs(counts: TestCounts): number {
  return counts.unit * UNIT_MS + counts.integration * INTEGRATION_MS + counts.e2e * E2E_MS;
}

export function toSeconds(milliseconds: number): number {
  return Math.round(milliseconds / 100) / 10;
}

/** 本数を変えずに、上限に収まるところまで E2E と統合テストを削る（その分をユニットに回す） */
export function proposeRebalance(counts: TestCounts): TestCounts {
  const total = totalTestCount(counts);
  const e2e = Math.min(counts.e2e, Math.floor((total * MAX_E2E_PERCENT) / 100));
  const integration = Math.min(
    counts.integration,
    Math.floor((total * MAX_INTEGRATION_PERCENT) / 100)
  );

  return { unit: total - e2e - integration, integration, e2e };
}

export function speedupRatio(before: TestCounts, after: TestCounts): number {
  const afterMs = estimateSuiteMs(after);

  return afterMs === 0 ? 0 : Math.round((estimateSuiteMs(before) / afterMs) * 10) / 10;
}

export type StepId = 'checkout' | 'setup-node' | 'install' | 'typecheck' | 'lint' | 'test' | 'build';

const REQUIRED_CI_STEPS = [
  'checkout',
  'setup-node',
  'install',
  'typecheck',
  'lint',
  'test',
  'build',
] as const;

/** [先に置くもの, 後に置くもの] の組 */
const CI_ORDER_RULES: readonly (readonly [StepId, StepId])[] = [
  ['install', 'typecheck'],
  ['typecheck', 'test'],
  ['test', 'build'],
  ['install', 'lint'],
];

export function findMissingSteps(steps: readonly StepId[]): StepId[] {
  return REQUIRED_CI_STEPS.filter((step) => !steps.includes(step));
}

export function checkStepOrder(steps: readonly StepId[]): string[] {
  const problems: string[] = [];

  for (const [before, after] of CI_ORDER_RULES) {
    const beforeIndex = steps.indexOf(before);
    const afterIndex = steps.indexOf(after);

    if (beforeIndex === -1 || afterIndex === -1) {
      continue;
    }
    if (beforeIndex > afterIndex) {
      problems.push(`${before} は ${after} より前に置く`);
    }
  }

  return problems;
}

// ===========================================================================
// 問題7：1本のリクエストを通す（S20・S21・S24・S25・S26・S27・S17・S18）
// ===========================================================================

export const productQuerySchema = z.object({
  category: z.enum(CATEGORY_SLUGS).nullable().catch(null),
  sort: z.enum(SORT_KEYS).catch('price-asc'),
  page: z.coerce.number().int().min(1).catch(1),
});

export type ProductQueryInput = z.infer<typeof productQuerySchema>;

/** キャッシュキーは「同じ条件なら同じ文字列」になるように、条件から機械的に作る */
export function buildProductsCacheKey(query: ProductQueryInput): string {
  return [
    'products',
    `category=${query.category ?? 'all'}`,
    `sort=${query.sort}`,
    `page=${query.page}`,
  ].join(':');
}

export type ApiRequest = {
  method: 'GET' | 'POST';
  path: string;
  query: Record<string, string | undefined>;
  headers: Record<string, string>;
  user: SessionUser | undefined;
  now: number;
};

export type ProductsApiDeps = {
  rateLimitStore: Map<string, RateLimitState>;
  cache: TtlCache<readonly ProductRow[]>;
  logger: Logger;
  /** データベースから商品を取る。失敗もタイムアウトも起こりうる */
  load: (categoryId: number | null, signal: AbortSignal) => Promise<readonly ProductRow[]>;
  timeoutMs: number;
  retries: number;
};

export type ApiOutcome =
  | { kind: 'ok'; status: 200; count: number; cacheHit: boolean }
  | { kind: 'error'; status: number; message: string; headers: Record<string, string> };

export async function handleProductsRequest(
  deps: ProductsApiDeps,
  request: ApiRequest
): Promise<ApiOutcome> {
  // ① 出どころの確認。Server Actions と違い、ルートハンドラは自分で守る
  if (request.method !== 'GET') {
    const origin = request.headers['origin'] ?? null;
    const host = request.headers['host'] ?? null;

    if (!isTrustedOrigin(origin, host)) {
      return failOutcome(deps, request, { kind: 'forbidden' });
    }
  }

  // ② レート制限。相手とパスごとに数える（時刻は引数で受け取る）
  const clientKey = `${request.headers['x-forwarded-for'] ?? 'unknown'}|${request.path}`;
  const decision = decideRateLimit(deps.rateLimitStore, clientKey, request.now, API_RATE_LIMIT);

  if (decision.kind === 'blocked') {
    return failOutcome(deps, request, {
      kind: 'rate_limited',
      retryAfterSeconds: decision.retryAfterSeconds,
    });
  }

  // ③ クエリの検証。壊れた値は既定値に落とす（一覧が500になるのは大げさ）
  const query = productQuerySchema.parse(request.query);
  const categoryId = query.category === null ? null : findCategoryIdBySlug(query.category);
  const cacheKey = buildProductsCacheKey(query);

  // ④ キャッシュを引く。当たれば、ここで終わり
  const cached = deps.cache.get(cacheKey, request.now);

  if (cached !== undefined) {
    return okOutcome(deps, request, cacheKey, cached, true);
  }

  // ⑤ 外れたらデータベースを見る。制限時間つき・失敗したら指数バックオフで再試行
  const loaded = await loadProducts(deps, categoryId);

  if (loaded.kind === 'error') {
    return failOutcome(deps, request, loaded.error);
  }

  deps.cache.set(cacheKey, loaded.value, request.now, [
    PRODUCTS_TAG,
    categoryTag(query.category ?? 'all'),
  ]);

  return okOutcome(deps, request, cacheKey, loaded.value, false);
}

/** 例外を投げる世界（タイムアウト・通信の失敗）と Result の世界の境界 */
async function loadProducts(
  deps: ProductsApiDeps,
  categoryId: number | null
): Promise<Result<readonly ProductRow[], CheckoutFailure>> {
  try {
    const rows = await retryWithBackoff(
      () => withTimeout((signal) => deps.load(categoryId, signal), deps.timeoutMs),
      { retries: deps.retries, baseMs: 1 }
    );

    return ok(rows);
  } catch (error: unknown) {
    const internalMessage = isAbortLike(error)
      ? `制限時間 ${deps.timeoutMs}ms を超えました`
      : toMessage(error);

    return fail({ kind: 'unexpected', internalMessage });
  }
}

function okOutcome(
  deps: ProductsApiDeps,
  request: ApiRequest,
  cacheKey: string,
  rows: readonly ProductRow[],
  cacheHit: boolean
): ApiOutcome {
  deps.logger.log('info', `${request.method} ${request.path} を処理しました`, {
    cacheKey,
    cacheHit,
    count: rows.length,
    userId: request.user?.id,
  });

  return { kind: 'ok', status: 200, count: rows.length, cacheHit };
}

function failOutcome(
  deps: ProductsApiDeps,
  request: ApiRequest,
  failure: CheckoutFailure
): ApiOutcome {
  const response = toApiFailure(failure);

  deps.logger.log(
    response.status >= 500 ? 'error' : 'warn',
    `${request.method} ${request.path} を処理できませんでした`,
    {
      failureKind: failure.kind,
      detail: failure.kind === 'unexpected' ? failure.internalMessage : describeFailure(failure),
    }
  );

  return {
    kind: 'error',
    status: response.status,
    message: response.body.error.message,
    headers: response.headers,
  };
}

export function formatApiOutcome(label: string, outcome: ApiOutcome): string {
  return outcome.kind === 'ok'
    ? `${label} → 200 / ${outcome.count}件 / ${outcome.cacheHit ? 'hit' : 'miss'}`
    : `${label} → ${outcome.status} ${outcome.message}`;
}

// ===========================================================================
// 問題8：リリース前の監査（S25・S26・S27・S28）
// ===========================================================================

export type Severity = 'critical' | 'warning';

export type Finding = { severity: Severity; code: string; message: string };

const REQUIRED_COOKIE_ATTRIBUTES = [
  'HttpOnly',
  'Secure',
  'SameSite=Lax',
  'Path=/',
  'Max-Age=',
] as const;

const REQUIRED_SECURITY_HEADERS = [
  'Content-Security-Policy',
  'X-Content-Type-Options',
  'Referrer-Policy',
  'X-Frame-Options',
  'Strict-Transport-Security',
] as const;

const PUBLIC_ENV_PREFIX = 'NEXT_PUBLIC_';

const SECRET_NAME_PARTS = ['SECRET', 'TOKEN', 'PASSWORD', 'PRIVATE', 'KEY', 'CREDENTIAL'] as const;

export type ReleaseConfig = {
  setCookie: string;
  securityHeaders: Record<string, string>;
  envNames: readonly string[];
  ciSteps: readonly StepId[];
  pendingMigrations: readonly string[];
  migrateCommand: 'migrate dev' | 'migrate deploy';
  dockerfile: string;
  testCounts: TestCounts;
};

export function auditRelease(config: ReleaseConfig): Finding[] {
  const findings: Finding[] = [];

  // ① Cookie の属性（S25）
  const missingCookie = REQUIRED_COOKIE_ATTRIBUTES.filter(
    (attribute) => !config.setCookie.includes(attribute)
  );

  if (missingCookie.length > 0) {
    findings.push({
      severity: 'critical',
      code: 'cookie_attributes',
      message: `Cookie に ${missingCookie.join(', ')} が付いていません`,
    });
  }

  // ② セキュリティヘッダと CSP（S26）
  const missingHeaders = REQUIRED_SECURITY_HEADERS.filter(
    (name) => (config.securityHeaders[name] ?? '') === ''
  );

  if (missingHeaders.length > 0) {
    findings.push({
      severity: 'critical',
      code: 'security_headers',
      message: `ヘッダが足りません（${missingHeaders.join(', ')}）`,
    });
  }
  if ((config.securityHeaders['Content-Security-Policy'] ?? '').includes("'unsafe-inline'")) {
    findings.push({
      severity: 'critical',
      code: 'csp_unsafe_inline',
      message: "CSP に 'unsafe-inline' が入っています",
    });
  }

  // ③ ブラウザに埋まる秘密（S26・S28）
  const leaked = config.envNames
    .filter((name) => name.startsWith(PUBLIC_ENV_PREFIX))
    .filter((name) => SECRET_NAME_PARTS.some((part) => name.toUpperCase().includes(part)));

  if (leaked.length > 0) {
    findings.push({
      severity: 'critical',
      code: 'public_secret',
      message: `ブラウザに埋まる秘密があります（${leaked.join(', ')}）`,
    });
  }

  // ④ CI の中身と順序（S28）
  const missingSteps = findMissingSteps(config.ciSteps);

  if (missingSteps.length > 0) {
    findings.push({
      severity: 'critical',
      code: 'ci_missing_step',
      message: `CI に ${missingSteps.join(', ')} がありません`,
    });
  }

  const orderProblems = checkStepOrder(config.ciSteps);

  if (orderProblems.length > 0) {
    findings.push({
      severity: 'warning',
      code: 'ci_step_order',
      message: orderProblems.join(' / '),
    });
  }

  // ⑤ マイグレーション（S28）
  if (config.pendingMigrations.length > 0) {
    findings.push({
      severity: 'critical',
      code: 'migrations_pending',
      message: `未適用のマイグレーションが${config.pendingMigrations.length}件あります（${config.pendingMigrations.join(', ')}）`,
    });
  }
  if (config.migrateCommand === 'migrate dev') {
    findings.push({
      severity: 'critical',
      code: 'migrate_command',
      message: '本番では migrate deploy を使ってください',
    });
  }

  // ⑥ 本番用イメージ（S28）
  if (!/^USER\s+node$/m.test(config.dockerfile)) {
    findings.push({
      severity: 'critical',
      code: 'docker_root',
      message: '実行段に USER node がありません（root で動きます）',
    });
  }
  if (!config.dockerfile.includes('.next/standalone')) {
    findings.push({
      severity: 'warning',
      code: 'docker_fat_image',
      message: 'standalone の出力を使っていません（イメージが太ります）',
    });
  }

  // ⑦ テストの配分（S28。問題6 の判定をそのまま使う）
  const balance = judgeTestBalance(config.testCounts);

  if (balance.kind === 'ice-cream-cone' || balance.kind === 'unit-too-few') {
    findings.push({
      severity: 'warning',
      code: 'test_balance',
      message: describeJudgement(balance),
    });
  }

  return findings;
}

export function canRelease(findings: readonly Finding[]): boolean {
  return findings.every((finding) => finding.severity !== 'critical');
}

export function formatFindings(findings: readonly Finding[]): string[] {
  return findings.map((finding) => `[${finding.severity}] ${finding.code}: ${finding.message}`);
}

export function summarizeFindings(findings: readonly Finding[]): string {
  const critical = findings.filter((finding) => finding.severity === 'critical').length;

  return `${canRelease(findings) ? '出せる' : '出せない'}（critical ${critical}件 / warning ${findings.length - critical}件）`;
}
