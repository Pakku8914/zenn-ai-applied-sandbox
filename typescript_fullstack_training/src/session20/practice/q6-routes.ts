// 問題6（発展）: ルート表の中身。
// ルーター（q6-router.ts）は「どこへ渡すか」だけを知り、
// こちらのハンドラは「何をするか」だけを知る。役割が分かれた。

import { findCatalogItem, loadCatalogSafely } from '../../session18/shop';
import { toErrorPayload, toHttpStatus } from '../error-status';
import { sendJson } from '../http-tools';
import type { Route } from './q6-router';

export const shopRoutes: readonly Route[] = [
  {
    method: 'GET',
    path: '/api/health',
    handler: async (_req, res) => {
      sendJson(res, 200, { status: 'ok' });
    },
  },
  {
    method: 'GET',
    path: '/api/products/:id',
    handler: async (_req, res, params) => {
      // params の値は Record<string, string> なので、取り出すと string | undefined。
      // 「:id があるルートに来たのだから必ずある」は型に書かれていない。
      // これを型で保証してくれるのがフレームワークのルーティングの仕事。
      const raw = params['id'];

      if (raw === undefined || !/^\d+$/.test(raw)) {
        sendJson(res, 400, {
          error: { kind: 'invalid_path_param', message: '商品IDは数字で指定してください' },
        });
        return;
      }

      const catalog = await loadCatalogSafely();
      if (catalog.kind === 'error') {
        sendJson(res, toHttpStatus(catalog.error), toErrorPayload(catalog.error));
        return;
      }

      const found = findCatalogItem(catalog.value, Number(raw));
      if (found.kind === 'error') {
        sendJson(res, toHttpStatus(found.error), toErrorPayload(found.error));
        return;
      }
      sendJson(res, 200, found.value);
    },
  },
];
