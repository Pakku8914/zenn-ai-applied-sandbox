// 問題6 のサーバーを手で起動する。
// 実行: docker compose exec ts npx tsx src/session20/practice/start-q6.ts
// 停止: Ctrl + C

import { createRoutedServer } from './q6-router';
import { shopRoutes } from './q6-routes';

const port = Number(process.env['PORT'] ?? 3000);

const server = createRoutedServer(shopRoutes, (caught: unknown) => {
  console.error('[routed-server] 想定外のエラー', caught);
});

server.listen(port, () => {
  console.log(`起動しました: http://localhost:${port}/api/health`);
});
