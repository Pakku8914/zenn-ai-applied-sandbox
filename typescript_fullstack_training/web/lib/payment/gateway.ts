// 決済ゲートウェイのスタブ（セッション24で導入し、最終プロジェクトまで同じ形で使う）。
//
// 本物の決済サービスにはつながない。読者に課金も外部アカウント登録もさせないためである。
// 代わりに「請求金額の下2桁」で結果を決める約束にしてあり、失敗の再現がいつでもできる。
//   下2桁が 01 → カードが拒否された（failed）
//   下2桁が 02 → 応答が返ってこなかった（pending。成功か失敗か分からない状態）
//   それ以外   → 成功（succeeded）
//
// Webhook の署名検証・返金・二重決済の完全な防止は最終プロジェクトで扱う。

/** 決済結果。判別タグは本書共通の kind */
export type PaymentResult =
  | { kind: 'succeeded'; paymentId: string }
  | { kind: 'failed'; reason: 'card_declined' | 'insufficient_funds' | 'network_error' }
  | { kind: 'pending'; paymentId: string };

export type ChargeInput = {
  /** 二重決済を防ぐ冪等キー。同じキーの再送は同じ結果を返す */
  idempotencyKey: string;
  /** 請求金額（円・整数） */
  amount: number;
  orderId: string;
};

export interface PaymentGateway {
  charge(input: ChargeInput): Promise<PaymentResult>;
}

/**
 * 冪等キーは「1回の支払い」に対して1つ決める。
 * 注文 ID から作れば、通信が失敗して読者が再送しても同じキーになる。
 */
export function buildIdempotencyKey(orderId: string): string {
  return `charge-${orderId}`;
}

/** 金額の下2桁から結果を決める純粋な関数。テストで失敗系を再現するための仕掛け */
export function decidePaymentResult(input: ChargeInput): PaymentResult {
  const lastTwoDigits = Math.abs(Math.trunc(input.amount)) % 100;
  const paymentId = `pay_${input.idempotencyKey}`;

  switch (lastTwoDigits) {
    case 1:
      return { kind: 'failed', reason: 'card_declined' };
    case 2:
      return { kind: 'pending', paymentId };
    default:
      return { kind: 'succeeded', paymentId };
  }
}

/** 結果を利用者向けの日本語にする。網羅性は never で確かめる（セッション12） */
export function describePaymentResult(result: PaymentResult): string {
  switch (result.kind) {
    case 'succeeded':
      return 'お支払いが完了しました';
    case 'pending':
      return 'お支払いの確認中です。結果が分かりしだいお知らせします';
    case 'failed':
      switch (result.reason) {
        case 'card_declined':
          return 'カードが利用できませんでした。別のカードをお試しください';
        case 'insufficient_funds':
          return '残高が不足しています';
        case 'network_error':
          return '通信に失敗しました。しばらくしてからお試しください';
        default: {
          const unreachable: never = result.reason;

          throw new Error(`未知の失敗理由です: ${String(unreachable)}`);
        }
      }
    default: {
      const unreachable: never = result;

      throw new Error(`未知の決済結果です: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * スタブの実装。冪等キーごとに結果を覚えておき、同じキーの2回目は課金しない。
 * 本物のゲートウェイもこれと同じ約束（同じキーなら同じ結果）を提供している。
 */
export class StubPaymentGateway implements PaymentGateway {
  readonly #results = new Map<string, PaymentResult>();
  #chargeCount = 0;

  /** 実際に課金を試みた回数。テストで「2回叩いても1回しか課金しない」ことを確かめるために公開する */
  get chargeCount(): number {
    return this.#chargeCount;
  }

  async charge(input: ChargeInput): Promise<PaymentResult> {
    const remembered = this.#results.get(input.idempotencyKey);

    if (remembered !== undefined) {
      return remembered;
    }

    this.#chargeCount += 1;

    const result = decidePaymentResult(input);

    this.#results.set(input.idempotencyKey, result);

    return result;
  }
}

// ---------------------------------------------------------------------------
// 最終プロジェクト：アプリ全体で1つのゲートウェイを共有する
//
// このスタブは冪等キーの記憶を自分の Map に持っている。呼ぶたびに new すると
// その記憶が毎回まっさらになり、「同じキーなら同じ結果」の約束が守れない。
// そこで lib/db.ts の PrismaClient と同じ方法で globalThis に覚えさせ、
// 開発中のホットリロードでも作り直されないようにする。
//
// 本物の決済サービスでは冪等キーの記憶は相手側にあるので、この工夫は要らない。
// ---------------------------------------------------------------------------

const globalForGateway = globalThis as unknown as {
  paymentGateway?: StubPaymentGateway;
};

/**
 * 共有のゲートウェイを返す。戻り値の型を PaymentGateway にしてあるので、
 * 呼ぶ側はスタブであることに依存できない（＝本物に差し替えても直す場所が無い）。
 */
export function getPaymentGateway(): PaymentGateway {
  const existing = globalForGateway.paymentGateway;

  if (existing !== undefined) {
    return existing;
  }

  const created = new StubPaymentGateway();

  globalForGateway.paymentGateway = created;

  return created;
}
