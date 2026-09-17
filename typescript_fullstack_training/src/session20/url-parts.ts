// セッション20「WebとHTTPの基礎・Node.jsサーバー」
//
// URL を部品に分解する。
// リクエストの req.url には「/api/products?q=soap」のような相対パスしか入らないため、
// URL として扱うには基準（base）を足して絶対 URL に組み立て直す必要がある。

import type { IncomingMessage } from 'node:http';

/** URL の部品。ブラウザのアドレス欄に入る文字列を分解した結果 */
export type UrlParts = {
  protocol: string;
  hostname: string;
  port: string;
  pathname: string;
  search: string;
  hash: string;
};

/** 絶対 URL を部品に分解する */
export function describeUrl(input: string): UrlParts {
  const url = new URL(input);

  return {
    protocol: url.protocol,
    hostname: url.hostname,
    port: url.port,
    pathname: url.pathname,
    search: url.search,
    hash: url.hash,
  };
}

/** 分解した部品を1行ずつの文字列にする（表示用） */
export function formatUrlParts(input: string): string {
  const parts = describeUrl(input);

  return [
    `protocol: ${parts.protocol}`,
    `hostname: ${parts.hostname}`,
    `port: ${parts.port === '' ? '(既定値)' : parts.port}`,
    `pathname: ${parts.pathname}`,
    `search: ${parts.search === '' ? '(なし)' : parts.search}`,
    `hash: ${parts.hash === '' ? '(なし)' : parts.hash}`,
  ].join('\n');
}

/**
 * リクエストから絶対 URL を組み立てる。
 * host ヘッダはクライアントが自由に書ける値なので信用しない。
 * ここではパスとクエリだけを使うので、base の中身は何でもよい。
 */
export function toRequestUrl(req: IncomingMessage): URL {
  const host = req.headers.host ?? 'localhost';
  return new URL(req.url ?? '/', `http://${host}`);
}

/** クエリから値を1つ取り出す。無ければ既定値を返す */
export function getQuery(url: URL, key: string, fallback = ''): string {
  return url.searchParams.get(key) ?? fallback;
}
