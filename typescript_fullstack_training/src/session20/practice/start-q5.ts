// 問題5 のサーバーを手で起動する。
// 実行: docker compose exec ts npx tsx src/session20/practice/start-q5.ts
// 停止: Ctrl + C
//
// 確認例（ターミナル2）:
//   curl -i -X PUT -H 'Content-Type: application/json' \
//     -d '{"quantityInput":"2"}' http://localhost:3000/api/cart/1
//   curl -i http://localhost:3000/api/cart

import { createCartServer } from './q5-cart-put';

const port = Number(process.env['PORT'] ?? 3000);

createCartServer().listen(port, () => {
  console.log(`起動しました: http://localhost:${port}/api/cart`);
});
