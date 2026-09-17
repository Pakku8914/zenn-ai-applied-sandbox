// 問題4: GET /api/categories を返すサーバーを作る。

import { createServer } from 'node:http';
import type { Server } from 'node:http';
import { loadCategories } from '../../session17/catalog';
import type { Category } from '../../session17/catalog';
import { tryCatchAsync } from '../../session18/result';
import { sendJson, withErrorHandling } from '../http-tools';
import { toRequestUrl } from '../url-parts';

export type CategoryLoader = () => Promise<Category[]>;

export type CategoryServerOptions = {
  onError?: (error: unknown) => void;
  /** 読み込みを差し替えられるようにしておく（失敗の再現に使う） */
  loadCategories?: CategoryLoader;
};

export function createCategoryServer(options: CategoryServerOptions = {}): Server {
  const onError =
    options.onError ??
    ((caught: unknown) => {
      console.error('[category-server] 想定外のエラー', caught);
    });
  const loader = options.loadCategories ?? loadCategories;

  return createServer(
    withErrorHandling(async (req, res) => {
      const url = toRequestUrl(req);
      const method = req.method ?? 'GET';

      if (url.pathname !== '/api/categories') {
        sendJson(res, 404, {
          error: {
            kind: 'route_not_found',
            message: `そのURLはありません: ${method} ${url.pathname}`,
          },
        });
        return;
      }

      if (method !== 'GET') {
        res.setHeader('Allow', 'GET');
        sendJson(res, 405, {
          error: { kind: 'method_not_allowed', message: 'このURLでは GET だけを使えます' },
        });
        return;
      }

      // 読み込みは例外を投げうるので、境界で Result に変える
      const loaded = await tryCatchAsync(loader);

      if (loaded.kind === 'error') {
        sendJson(res, 503, {
          error: {
            kind: 'categories_unavailable',
            message: 'サーバー側の問題でリクエストを処理できませんでした',
          },
        });
        return;
      }
      sendJson(res, 200, { count: loaded.value.length, items: loaded.value });
    }, onError)
  );
}
