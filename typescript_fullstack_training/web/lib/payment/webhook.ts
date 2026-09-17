// 決済 Webhook の署名検証とペイロードの検証（最終プロジェクト）。
//
// Webhook は「相手が勝手に叩いてくる POST」である。Cookie もセッションも無いので、
// 認証の役割を果たすのは署名だけである。したがって、
//   1. 署名を確かめる（誰が送ったか）
//   2. 形を確かめる（何が書いてあるか）
// の2段を通るまで、本文の中身をいっさい信用してはいけない。
//
// このファイルにはデータベースを触る処理を入れない。判定だけを純粋な関数として
// 置くことで、同じ実装を src/final/verify.ts と src/final/final.test.ts で
// 検証できる（web を src から import できないため、あちらには同じ仕様を写している）。

import { createHmac, timingSafeEqual } from 'node:crypto';
import { z } from 'zod';
import type { OrderStatus } from '@/lib/order-status';

/** 署名を載せるヘッダの名前。Headers.get は大文字小文字を区別しない */
export const SIGNATURE_HEADER = 'x-signature';

/** 使ったアルゴリズムを値に埋める。将来 sha512 に変えても両方を受けられる */
export const SIGNATURE_PREFIX = 'sha256=';

/**
 * 本文に署名を付ける。
 * 送り手（決済サービス）と受け手（このアプリ）が同じ秘密を持ち、
 * 同じ計算をするからこそ一致する。ハッシュ化と違い、鍵を知らない者は作れない。
 */
export function signWebhookBody(body: string, secret: string): string {
  const digest = createHmac('sha256', secret).update(body, 'utf8').digest('hex');

  return `${SIGNATURE_PREFIX}${digest}`;
}

/**
 * 署名を検証する。
 * - ヘッダが無い・接頭辞が違う場合は false を返す（例外にしない）
 * - 比較は timingSafeEqual。長さが違うと例外を投げるので、先に長さを確かめる
 */
export function verifyWebhookSignature(
  body: string,
  header: string | null | undefined,
  secret: string
): boolean {
  if (header === null || header === undefined || !header.startsWith(SIGNATURE_PREFIX)) {
    return false;
  }

  const expected = Buffer.from(signWebhookBody(body, secret), 'utf8');
  const received = Buffer.from(header, 'utf8');

  // 長さが違えばそもそも別物。ここで返さないと timingSafeEqual が例外を投げる
  if (expected.length !== received.length) {
    return false;
  }

  // 1文字目から違っていても最後まで比べる（比較にかかる時間から正解を推測されないため）
  return timingSafeEqual(expected, received);
}

/** Webhook のペイロード。API契約で決めた5つのフィールド */
export const webhookEventSchema = z.object({
  eventId: z.string({ error: 'eventId が必要です' }).min(1, { error: 'eventId が必要です' }),
  type: z.enum(['payment.succeeded', 'payment.failed']),
  paymentId: z.string().min(1),
  // JSON では数値でも文字列でも届きうるので、境界で数値に寄せる
  orderId: z.coerce.number().int().positive(),
  amount: z.coerce.number().int().min(0),
});

export type PaymentWebhookEvent = z.infer<typeof webhookEventSchema>;

/** 生の本文をイベントに変換する。壊れていれば null（例外を外に出さない） */
export function parseWebhookBody(raw: string): PaymentWebhookEvent | null {
  let json: unknown;

  try {
    json = JSON.parse(raw);
  } catch {
    return null;
  }

  const parsed = webhookEventSchema.safeParse(json);

  return parsed.success ? parsed.data : null;
}

/** Webhook を適用した結果。判別タグは本書共通の kind */
export type WebhookOutcome =
  | { kind: 'applied'; orderId: number; status: 'paid' | 'cancelled' }
  | { kind: 'duplicate'; eventId: string }
  | { kind: 'already_settled'; orderId: number; status: OrderStatus }
  | { kind: 'unknown_order'; orderId: number }
  | { kind: 'amount_mismatch'; orderId: number; expected: number; received: number };

/**
 * 結果を HTTP のステータスコードに翻訳する。
 *
 * 2xx は送り手にとって「もう再送しなくてよい」という返事である。
 * だから重複・処理済みには 200 を返す（400 を返すと永遠に再送され続ける）。
 * 人が調べる必要がある食い違いだけ 4xx にする。
 */
export function statusForOutcome(outcome: WebhookOutcome): 200 | 404 | 409 {
  switch (outcome.kind) {
    case 'applied':
    case 'duplicate':
    case 'already_settled':
      return 200;
    case 'unknown_order':
      return 404;
    case 'amount_mismatch':
      return 409;
    default: {
      const unreachable: never = outcome;

      throw new Error(`未知の結果です: ${JSON.stringify(unreachable)}`);
    }
  }
}

// ---------------------------------------------------------------------------
// 受信済みイベントの記録
//
// 置き場所はサーバーのメモリ（Set）である。lib/session.ts と同じ割り切りで、
// 学習のために道具を増やさないため。プロセスを再起動すると消えるので、
// 再起動直後に同じ eventId が来れば重複を見逃す。
//
// 見逃しても壊れないように、本当の砦は「条件付き更新」に置いてある
// （lib/checkout.ts の advanceOrderStatus は pending の行だけを更新するので、
// 2回目の適用は 0 件になる）。この Set は速い1段目の関所にすぎない。
// 実務では webhook_events テーブルに eventId を主キーで入れ、挿入の失敗で弾く。
// ---------------------------------------------------------------------------

const globalForEvents = globalThis as unknown as {
  paymentWebhookEvents?: Set<string>;
};

const processedEvents: Set<string> = globalForEvents.paymentWebhookEvents ?? new Set<string>();

globalForEvents.paymentWebhookEvents = processedEvents;

export function isProcessedEvent(eventId: string): boolean {
  return processedEvents.has(eventId);
}

export function markEventProcessed(eventId: string): void {
  processedEvents.add(eventId);
}
