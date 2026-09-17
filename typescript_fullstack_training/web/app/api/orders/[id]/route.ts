// GET /api/orders/12 — 自分の注文1件を JSON で返す（セッション26）。
//
// この口は middleware だけでは守れない。middleware が確かめられるのは
// 「Cookie があるか」までで、しかも /api は認証が必要なページとして
// 登録していない（レート制限の対象にはしている）。
// つまりルートハンドラは、自分で認証と認可を書く必要がある。
//
// 認可の要点は findOrderForUser(orderId, userId) を使うこと。userId を
// 渡さないと型エラーになるので、認可の確認を忘れられない（セッション25）。

import { statusForFailure } from '@/lib/authz';
import { getSessionUser } from '@/lib/session';
// 最終プロジェクトで問い合わせを lib/order-repository.ts に集約した。
// 明細と決済も同じ1回の問い合わせで取れるようになったので、応答に含める
import { findOrderDetailForUser } from '@/lib/order-repository';

// ログインしている人ごとに内容が変わる応答なので、ビルド時に固定しない。
export const dynamic = 'force-dynamic';

// 個人の情報を含む応答は、途中の機械に保存させない（セッション27で詳しく扱う）。
const PRIVATE_HEADERS: Record<string, string> = { 'Cache-Control': 'no-store' };

// ルートハンドラのファイルから export してよいのは GET などの決まった名前だけなので、
// 補助の関数は export しない（余分な export はビルド時の型チェックで弾かれる）。
/** URL の一部を注文IDに変換する。1以上の整数だけを通す */
function parseOrderId(raw: string): number | null {
  if (!/^[1-9][0-9]{0,9}$/.test(raw)) {
    return null;
  }

  return Number(raw);
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<Response> {
  // 1. 認証：誰なのかを先に確かめる（Cookie の有無ではなくセッションの中身を見る）
  const user = await getSessionUser();

  if (user === undefined) {
    return Response.json(
      { error: 'unauthenticated', message: 'ログインが必要です' },
      { status: statusForFailure({ kind: 'unauthenticated' }), headers: PRIVATE_HEADERS }
    );
  }

  // 2. 入力の検証：URL から来た値を、そのままデータベースに渡さない
  const { id } = await params;
  const orderId = parseOrderId(id);

  if (orderId === null) {
    return Response.json(
      { error: 'invalid_id', message: '注文IDの形式が正しくありません' },
      { status: 400, headers: PRIVATE_HEADERS }
    );
  }

  // 3. 認可：「自分のものか」を問い合わせの条件に入れる
  const order = await findOrderDetailForUser(orderId, user.id);

  if (order === undefined) {
    // 他人の注文と、存在しない注文を区別しない。区別すると
    // 「注文 #12 は存在する」という事実だけが伝わってしまう
    return Response.json(
      { error: 'order_not_found', message: '注文が見つかりません' },
      { status: 404, headers: PRIVATE_HEADERS }
    );
  }

  // 4. 応答：必要な項目だけを選んで返す。
  // userId・冪等キーのような内部の情報は載せない（漏らしても得がなく、損だけがある）
  return Response.json(
    {
      id: order.id,
      status: order.status,
      totalAmount: order.totalAmount,
      createdAt: order.createdAt.toISOString(),
      paymentStatus: order.payment === null ? null : order.payment.status,
      items: order.items.map((item) => ({
        productId: item.productId,
        productName: item.productName,
        quantity: item.quantity,
        unitPrice: item.unitPrice,
      })),
    },
    { headers: PRIVATE_HEADERS }
  );
}
