// GET /api/health — 設定が揃っているかを確かめる口（セッション26）。
//
// 環境変数の設定漏れは「動かしてみたら例外が出る」という形で、しかも
// たいてい本番で最初に気づく。それを避けるために、設定の状態を1か所で
// 見られるようにしておく。デプロイの直後にここを見れば分かる（セッション28で使う）。
//
// 返すのは「変数の名前」と「揃っているか」だけ。値は絶対に返さない。
// DATABASE_URL には利用者名とパスワードが含まれるので、返せば漏洩そのものになる。

import { describeEnvStatus } from '@/lib/env';

export const dynamic = 'force-dynamic';

export async function GET(): Promise<Response> {
  const status = describeEnvStatus(process.env);

  return Response.json(status, {
    // 設定が足りないなら 500。監視の仕組みが機械的に気づけるようにする
    status: status.ok ? 200 : 500,
    headers: { 'Cache-Control': 'no-store' },
  });
}
