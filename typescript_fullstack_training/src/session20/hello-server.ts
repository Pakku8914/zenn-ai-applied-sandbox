// セッション20「WebとHTTPの基礎・Node.jsサーバー」
//
// 最初のサーバー。どのパスに来ても同じ文章を返す。

import { createServer } from 'node:http';
import type { Server } from 'node:http';
import { sendText } from './http-tools';
import { toRequestUrl } from './url-parts';

/** Hello を返すだけのサーバーを作る（待ち受けの開始はまだしない） */
export function createHelloServer(): Server {
  return createServer((req, res) => {
    const url = toRequestUrl(req);
    const method = req.method ?? 'GET';

    sendText(res, 200, `Hello, ミニ雑貨ショップ!\nmethod=${method} path=${url.pathname}\n`);
  });
}
