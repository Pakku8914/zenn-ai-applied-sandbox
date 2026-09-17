// Hello サーバーを手で起動する。
// 実行: docker compose exec ts npx tsx src/session20/start-hello.ts
// 停止: Ctrl + C

import { createHelloServer } from './hello-server';

const port = Number(process.env['PORT'] ?? 3000);

createHelloServer().listen(port, () => {
  console.log(`起動しました: http://localhost:${port}/`);
});
