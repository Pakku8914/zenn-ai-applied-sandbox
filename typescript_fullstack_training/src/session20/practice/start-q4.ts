// 問題4 のサーバーを手で起動する。
// 実行: docker compose exec ts npx tsx src/session20/practice/start-q4.ts
// 停止: Ctrl + C

import { createCategoryServer } from './q4-categories-server';

const port = Number(process.env['PORT'] ?? 3000);

createCategoryServer().listen(port, () => {
  console.log(`起動しました: http://localhost:${port}/api/categories`);
});
