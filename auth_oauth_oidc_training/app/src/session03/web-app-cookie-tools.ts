// Set-Cookie を読み解き、Cookie を手で運んでリクエストを送るための小道具。
// ブラウザが自動でやっていることを手作業で再現します。
import type { Hono } from "hono";

export type ParsedCookie = {
  readonly name: string;
  readonly value: string;
  // 属性名は小文字に正規化して持つ（HttpOnly / httponly のどちらで来ても同じ扱いにする）
  readonly attributes: ReadonlyMap<string, string>;
};

export function parseSetCookie(header: string | null): ParsedCookie | undefined {
  if (header === null) {
    return undefined;
  }
  const [pair, ...rest] = header.split(";").map((segment) => segment.trim());
  const separator = pair === undefined ? -1 : pair.indexOf("=");
  if (pair === undefined || separator < 0) {
    return undefined;
  }
  const attributes = new Map<string, string>();
  for (const segment of rest) {
    const index = segment.indexOf("=");
    // HttpOnly や Secure のように値を持たない属性は空文字を値にする
    attributes.set(
      (index < 0 ? segment : segment.slice(0, index)).toLowerCase(),
      index < 0 ? "" : segment.slice(index + 1),
    );
  }
  return { name: pair.slice(0, separator), value: pair.slice(separator + 1), attributes };
}

/** HttpOnly・Secure のような値なし属性が付いているか */
export function hasFlag(cookie: ParsedCookie, flag: string): boolean {
  return cookie.attributes.has(flag.toLowerCase());
}

/** SameSite・Path のような値あり属性を取り出す */
export function attribute(cookie: ParsedCookie, name: string): string {
  return cookie.attributes.get(name.toLowerCase()) ?? "(なし)";
}

/** ブラウザが次のリクエストで送る Cookie ヘッダの形（name=value） */
export function cookieHeader(name: string, value: string): string {
  return `${name}=${value}`;
}

export type CallOptions = {
  method?: string;
  cookie?: string; // 送る Cookie ヘッダ（例: "sid=xxxx"）
  form?: Record<string, string>; // application/x-www-form-urlencoded で送る値
};

export type CallResult = {
  readonly status: number;
  readonly body: string;
  readonly setCookie: string | null;
};

/** Hono の app.request() でアプリを直接叩く。Cookie はブラウザの代わりに呼び出し側が運ぶ */
export async function call(app: Hono, path: string, options: CallOptions = {}): Promise<CallResult> {
  const headers: Record<string, string> = {};
  if (options.cookie !== undefined) {
    headers["cookie"] = options.cookie;
  }
  let body: string | undefined;
  if (options.form !== undefined) {
    headers["content-type"] = "application/x-www-form-urlencoded";
    body = new URLSearchParams(options.form).toString();
  }
  const res = await app.request(path, {
    method: options.method ?? "GET",
    headers,
    ...(body === undefined ? {} : { body }),
  });
  return { status: res.status, body: await res.text(), setCookie: res.headers.get("set-cookie") };
}
