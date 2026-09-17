// 検証用の小道具。Hono のアプリを一時的に HTTP サーバーとして起動し、fetch で叩けるようにします。
// ブラウザと違って fetch は Cookie を自動保存しないので、Cookie は呼び出し側が手で運びます。
import { serve } from "@hono/node-server";
import type { Hono } from "hono";

export type CallOptions = {
  method?: string;
  /** 送る Cookie ヘッダ（例: "sid=xxxx"） */
  cookie?: string;
  /** application/x-www-form-urlencoded で送るフォームの値 */
  form?: Record<string, string>;
};

export type CallResult = {
  readonly status: number;
  readonly body: string;
  readonly setCookie: string | null;
};

export type TestServer = {
  call(path: string, options?: CallOptions): Promise<CallResult>;
  close(): void;
};

export async function startServer(app: Hono, port: number): Promise<TestServer> {
  const server = serve({ fetch: app.fetch, port });
  const base = `http://127.0.0.1:${port}`;

  // 受付開始まで短い間隔で叩いて待つ（固定時間の sleep に頼らない）
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      await fetch(base);
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  return {
    async call(path, options = {}) {
      const headers: Record<string, string> = {};
      if (options.cookie !== undefined) {
        headers["cookie"] = options.cookie;
      }
      let body: string | undefined;
      if (options.form !== undefined) {
        headers["content-type"] = "application/x-www-form-urlencoded";
        body = new URLSearchParams(options.form).toString();
      }
      const res = await fetch(`${base}${path}`, {
        method: options.method ?? "GET",
        headers,
        // リダイレクトを自動で追わない（Location と Set-Cookie を自分の目で確かめるため）
        redirect: "manual",
        ...(body === undefined ? {} : { body }),
      });
      return { status: res.status, body: await res.text(), setCookie: res.headers.get("set-cookie") };
    },
    close() {
      server.close();
    },
  };
}
