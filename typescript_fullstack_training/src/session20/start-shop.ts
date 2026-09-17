// ショップの API サーバーを手で起動する。
// 実行: docker compose exec ts npx tsx src/session20/start-shop.ts
// 停止: Ctrl + C

import { createShopServer } from './shop-server';

const port = Number(process.env['PORT'] ?? 3000);

createShopServer().listen(port, () => {
  console.log(`起動しました: http://localhost:${port}/api/products`);
});
