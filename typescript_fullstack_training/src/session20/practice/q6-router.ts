// 問題6（発展）: 「ルート表」でルーティングを整理する。
// フレームワークがやっていることのうち、パスの照合とパスパラメータの取り出しを自分で作る。

import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { sendJson, withErrorHandling } from '../http-tools';
import { toRequestUrl } from '../url-parts';

/** パスパラメータ。'/api/products/:id' の :id が入る */
export type RouteParams = Record<string, string>;

export type RouteHandler = (
  req: IncomingMessage,
  res: ServerResponse,
  params: RouteParams
) => Promise<void>;

export type Route = {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** ':name' を含められるパスの形。例: '/api/products/:id' */
  path: string;
  handler: RouteHandler;
};

/** 照合の結果。判別タグは本書共通の kind */
export type RouteMatch =
  | { kind: 'matched'; route: Route; params: RouteParams }
  | { kind: 'method_not_allowed'; allowed: readonly string[] }
  | { kind: 'not_found' };

function assertNever(value: never): never {
  throw new Error(`未対応の照合結果があります: ${JSON.stringify(value)}`);
}

/** パスの形と実際のパスを照合し、パスパラメータを取り出す */
export function matchPath(pattern: string, pathname: string): RouteParams | undefined {
  const patternParts = pattern.split('/');
  const pathParts = pathname.split('/');

  if (patternParts.length !== pathParts.length) {
    return undefined;
  }

  const params: RouteParams = {};

  for (let index = 0; index < patternParts.length; index += 1) {
    // noUncheckedIndexedAccess が有効なので、取り出した値は string | undefined
    const expected = patternParts[index];
    const actual = pathParts[index];

    if (expected === undefined || actual === undefined) {
      return undefined;
    }

    if (expected.startsWith(':')) {
      // 空のパスパラメータ（'/api/products/'）は一致させない
      if (actual === '') {
        return undefined;
      }
      params[expected.slice(1)] = actual;
      continue;
    }

    if (expected !== actual) {
      return undefined;
    }
  }
  return params;
}

/**
 * ルート表から行き先を決める。
 * パスは一致するがメソッドが違う場合は、404 ではなく 405 の材料を返す。
 */
export function matchRoute(
  routes: readonly Route[],
  method: string,
  pathname: string
): RouteMatch {
  const allowed: string[] = [];

  for (const route of routes) {
    const params = matchPath(route.path, pathname);

    if (params === undefined) {
      continue;
    }
    if (route.method === method) {
      return { kind: 'matched', route, params };
    }
    allowed.push(route.method);
  }

  return allowed.length > 0 ? { kind: 'method_not_allowed', allowed } : { kind: 'not_found' };
}

/** ルート表からサーバーを作る。分岐の if がハンドラの外に出た */
export function createRoutedServer(
  routes: readonly Route[],
  onError: (error: unknown) => void
): Server {
  return createServer(
    withErrorHandling(async (req, res) => {
      const url = toRequestUrl(req);
      const method = req.method ?? 'GET';
      const matched = matchRoute(routes, method, url.pathname);

      switch (matched.kind) {
        case 'matched':
          await matched.route.handler(req, res, matched.params);
          return;
        case 'method_not_allowed':
          res.setHeader('Allow', matched.allowed.join(', '));
          sendJson(res, 405, {
            error: {
              kind: 'method_not_allowed',
              message: `このURLでは ${matched.allowed.join(' / ')} だけを使えます`,
            },
          });
          return;
        case 'not_found':
          sendJson(res, 404, {
            error: {
              kind: 'route_not_found',
              message: `そのURLはありません: ${method} ${url.pathname}`,
            },
          });
          return;
        default:
          return assertNever(matched);
      }
    }, onError)
  );
}
