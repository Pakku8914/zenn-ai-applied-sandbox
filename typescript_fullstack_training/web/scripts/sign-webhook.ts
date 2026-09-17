// 署名付きの Webhook 要求を組み立てる道具（最終プロジェクト）。
//
// 実行:
//   docker compose exec ts sh -c 'cd web && node --experimental-strip-types scripts/sign-webhook.ts 1 3641 payment.succeeded'
//
// 決済サービスの代わりに、こちらで署名を作って表示する。出てきた curl を
// そのまま実行すれば、本物の通知と区別できない要求を自分のアプリへ送れる。
//
// このファイルは lib/ から import せず、署名の計算だけを書き写している。
// node --experimental-strip-types は tsconfig の paths（@/...）を解釈しないためで、
// 「小さな道具は自己完結させる」という割り切りである（scripts/ の他のファイルと同じ）。

import { createHmac } from 'node:crypto';

/** lib/payment/webhook.ts と同じ接頭辞。値を変えるときは両方直す */
const SIGNATURE_PREFIX = 'sha256=';

/** lib/env.ts の DEV_PAYMENT_WEBHOOK_SECRET と同じ値 */
const DEV_SECRET = 'dev-only-webhook-secret';

type EventType = 'payment.succeeded' | 'payment.failed';

function parseEventType(raw: string | undefined): EventType {
  return raw === 'payment.failed' ? 'payment.failed' : 'payment.succeeded';
}

function parsePositiveInt(raw: string | undefined, label: string): number {
  const value = Number(raw);

  if (!Number.isInteger(value) || value <= 0) {
    // 引数の誤りはプログラムの使い方の誤り。Result にせず止める（セッション18）
    throw new Error(`${label} は1以上の整数で指定してください: ${String(raw)}`);
  }

  return value;
}

function main(): void {
  const orderId = parsePositiveInt(process.argv[2], '注文ID');
  const amount = parsePositiveInt(process.argv[3], '金額');
  const type = parseEventType(process.argv[4]);
  const eventId = process.argv[5] ?? `evt_${Date.now()}`;
  const secret = process.env['PAYMENT_WEBHOOK_SECRET'] ?? DEV_SECRET;

  // JSON.stringify した「この文字列そのもの」に署名する。
  // 送る側と受ける側で1バイトでも違えば署名は一致しない
  const body = JSON.stringify({
    eventId,
    type,
    paymentId: `pay_charge-${orderId}`,
    orderId,
    amount,
  });
  const signature = `${SIGNATURE_PREFIX}${createHmac('sha256', secret).update(body, 'utf8').digest('hex')}`;

  console.log(`body      : ${body}`);
  console.log(`signature : ${signature}`);
  console.log('');
  console.log('次のコマンドで送信できます（コンテナ内から実行してください）:');
  console.log('');
  console.log(
    [
      'curl -i -X POST http://localhost:3000/api/webhooks/payment \\',
      `  -H 'Content-Type: application/json' \\`,
      `  -H 'X-Signature: ${signature}' \\`,
      `  -d '${body}'`,
    ].join('\n')
  );
}

main();
