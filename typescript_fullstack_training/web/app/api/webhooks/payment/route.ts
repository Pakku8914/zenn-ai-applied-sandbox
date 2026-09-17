// POST /api/webhooks/payment — 決済サービスからの通知を受け取る（最終プロジェクト）。
//
// この口には Cookie もセッションも無い。相手は決済サービスの機械だからである。
// 代わりに署名（X-Signature）が身分証の役割を果たす。だから順序が決まっている。
//
//   1. 生の本文を文字列で受け取る（署名は「バイト列そのもの」に対して計算されている）
//   2. 署名を検証する。合わなければ 400 で即座に返す
//   3. 形（ペイロード）を検証する。壊れていれば 400
//   4. 適用する（重複と金額の食い違いはここで弾く）
//
// 2 と 3 を通るまで、本文の中身をログにも出さない（偽の通知の内容を記録しても意味がない）。

import { getWebhookSecret } from '@/lib/env';
import { getLogger } from '@/lib/logger';
import { applyPaymentEvent } from '@/lib/checkout';
import {
  SIGNATURE_HEADER,
  parseWebhookBody,
  statusForOutcome,
  verifyWebhookSignature,
} from '@/lib/payment/webhook';

// 通知は毎回内容が違うので、キャッシュも静的化もしない。
export const dynamic = 'force-dynamic';

export async function POST(request: Request): Promise<Response> {
  const logger = getLogger();

  // 1. request.json() を先に呼んではいけない。JSON にしてから文字列に戻すと
  //    空白やキーの順番が変わり、署名が一致しなくなる
  const rawBody = await request.text();
  const signature = request.headers.get(SIGNATURE_HEADER);

  // 2. 署名の検証。秘密が未設定なら getWebhookSecret が例外を投げる（本番のみ）
  if (!verifyWebhookSignature(rawBody, signature, getWebhookSecret())) {
    // 本文の中身は出さない。長さだけ残しておけば調査の手がかりになる
    logger.warn('webhook.invalid_signature', { bytes: rawBody.length });

    return Response.json({ error: 'invalid_signature' }, { status: 400 });
  }

  // 3. 形の検証。ここを通った値だけが PaymentWebhookEvent 型になる
  const event = parseWebhookBody(rawBody);

  if (event === null) {
    logger.warn('webhook.invalid_payload', { bytes: rawBody.length });

    return Response.json({ error: 'invalid_payload' }, { status: 400 });
  }

  // 4. 適用。同じ eventId の2回目は状態を変えずに 200 を返す
  const outcome = await applyPaymentEvent(event);
  const status = statusForOutcome(outcome);

  logger.info('webhook.processed', {
    eventId: event.eventId,
    type: event.type,
    outcome: outcome.kind,
    status,
  });

  return Response.json({ result: outcome.kind }, { status });
}
