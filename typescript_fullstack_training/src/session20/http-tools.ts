// セッション20「WebとHTTPの基礎・Node.jsサーバー」
//
// node:http でレスポンスを書く／リクエストのボディを読むための小さな道具。
// フレームワークが用意してくれているものを、この章では自分の手で書く。

import type { IncomingMessage, ServerResponse } from 'node:http';
import { tryCatch } from '../session18/result';
import type { Result } from '../session18/result';

/** 文字列を返す。charset を書き忘れると日本語が化ける */
export function sendText(res: ServerResponse, status: number, body: string): void {
  res.writeHead(status, {
    'Content-Type': 'text/plain; charset=utf-8',
    // 長さは「文字数」ではなく「バイト数」。日本語は1文字3バイトなので必ず測る
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

/** JSON を返す。文字列に直してから長さを測る */
export function sendJson(res: ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);

  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

/** 別の URL に案内する。本文は空でよく、行き先は Location ヘッダで伝える */
export function sendRedirect(
  res: ServerResponse,
  status: 301 | 302 | 303 | 307 | 308,
  location: string
): void {
  res.writeHead(status, { Location: location });
  res.end();
}

/** ボディの受け取り上限（64KB）。無制限に受け取るとメモリを食い尽くされる */
export const MAX_BODY_BYTES = 64 * 1024;

/** ボディが大きすぎた。呼び出し側は 413 を返す */
export class BodyTooLargeError extends Error {
  override readonly name = 'BodyTooLargeError';

  constructor(limitBytes: number) {
    super(`リクエストボディが大きすぎます（上限 ${limitBytes} バイト）`);
  }
}

/**
 * リクエストボディを文字列として受け取る。
 * ボディは1回で全部届くとは限らないので、届いた塊を順につなぐ。
 */
export async function readRequestBody(
  req: IncomingMessage,
  limitBytes = MAX_BODY_BYTES
): Promise<string> {
  // 文字列で受け取る指定。これを書かないとバイト列（Buffer）で届く
  req.setEncoding('utf-8');

  let body = '';
  let bytes = 0;

  for await (const chunk of req) {
    const text = String(chunk);
    bytes += Buffer.byteLength(text);

    if (bytes > limitBytes) {
      throw new BodyTooLargeError(limitBytes);
    }
    body += text;
  }
  return body;
}

/** JSON をパースする。JSON.parse は any を返すので unknown で受け直す */
export function parseJson(text: string): Result<unknown, Error> {
  return tryCatch<unknown>(() => JSON.parse(text));
}

export type CookieOptions = { maxAgeSeconds?: number; path?: string };

/**
 * Set-Cookie ヘッダの値を組み立てる。
 * HttpOnly / Secure / SameSite は最初から必ず付ける。
 * それぞれの意味は「セッション25：認証と認可」で解説する。
 */
export function buildSetCookieHeader(
  name: string,
  value: string,
  options: CookieOptions = {}
): string {
  const maxAgeSeconds = options.maxAgeSeconds ?? 3600;
  const path = options.path ?? '/';

  return [
    `${name}=${encodeURIComponent(value)}`,
    `Path=${path}`,
    `Max-Age=${maxAgeSeconds}`,
    'HttpOnly',
    'Secure',
    'SameSite=Lax',
  ].join('; ');
}

/** Cookie ヘッダ（'a=1; b=2'）を Map にする。ブラウザが送り返してくる側 */
export function parseCookieHeader(header: string | undefined): Map<string, string> {
  const cookies = new Map<string, string>();

  if (header === undefined) {
    return cookies;
  }

  for (const part of header.split(';')) {
    const separator = part.indexOf('=');

    if (separator <= 0) {
      continue;
    }
    const name = part.slice(0, separator).trim();
    const value = part.slice(separator + 1).trim();
    cookies.set(name, decodeURIComponent(value));
  }
  return cookies;
}

/** リクエストを処理する関数。失敗したら Promise が失敗する */
export type AsyncHandler = (req: IncomingMessage, res: ServerResponse) => Promise<void>;

/**
 * どんな例外が漏れても必ず 500 を返す安全網（セッション6の高階関数）。
 * これが無いと、1つのバグでレスポンスが返らずクライアントが待ち続ける。
 */
export function withErrorHandling(
  handler: AsyncHandler,
  onError: (error: unknown) => void
): (req: IncomingMessage, res: ServerResponse) => void {
  return (req, res) => {
    handler(req, res).catch((caught: unknown) => {
      onError(caught);

      // すでにヘッダを送っていたら、あとからステータスは変えられない
      if (res.headersSent) {
        res.end();
        return;
      }
      sendJson(res, 500, {
        error: { kind: 'internal_error', message: 'サーバー内部でエラーが発生しました' },
      });
    });
  };
}
