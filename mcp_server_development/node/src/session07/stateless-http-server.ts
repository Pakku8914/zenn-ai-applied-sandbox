/**
 * ステートレス運用の Streamable HTTP サーバー
 *
 * ステートフル版との差は 3 か所だけです。
 *   ① sessionIdGenerator: undefined（セッション ID を発行しない）
 *   ② リクエストごとにサーバーとトランスポートを作り、応答後に捨てる
 *   ③ GET と DELETE は 405（サーバー起点ストリームと破棄の概念が無い）
 */
import http from "node:http";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

import {
  DEFAULT_ENDPOINT,
  DEFAULT_HOST,
  DEFAULT_PORT,
  log,
  readJsonBody,
  sendError,
} from "./http-server.js";
import { type TrustPolicy, createTrustPolicy, firstHeader, verifyRequestTrust } from "./origin.js";

export type StatelessOptions = {
  readonly serverFactory: () => McpServer;
  readonly host?: string;
  readonly port?: number;
  readonly endpoint?: string;
  readonly trust?: TrustPolicy;
};

export function createStatelessListener(options: StatelessOptions): http.RequestListener {
  const endpoint = options.endpoint ?? DEFAULT_ENDPOINT;
  const trust = options.trust ?? createTrustPolicy();

  async function dispatch(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const pathname = new URL(req.url ?? "/", "http://placeholder").pathname;
    if (pathname !== endpoint) {
      sendError(res, 404, -32600, `このサーバーが公開しているのは ${endpoint} だけです。`);
      return;
    }

    // 検証はステートフル版とまったく同じ（同じ関数を使い回す）
    const verdict = verifyRequestTrust(req.headers, trust);
    if (!verdict.ok) {
      log(`拒否（${verdict.reason}）: origin=${firstHeader(req.headers.origin) ?? "(なし)"}`);
      sendError(res, 403, -32003, verdict.detail);
      return;
    }

    if (req.method !== "POST") {
      res.writeHead(405, { allow: "POST", "content-type": "application/json" });
      res.end(
        JSON.stringify({
          jsonrpc: "2.0",
          error: {
            code: -32600,
            message:
              "ステートレス運用では POST のみを受け付けます（GET のサーバー起点ストリームと DELETE は使えません）。",
          },
          id: null,
        }),
      );
      return;
    }

    const parsed = await readJsonBody(req);
    if (!parsed.ok) {
      sendError(res, parsed.reason === "too_large" ? 413 : 400, -32700, parsed.message);
      return;
    }

    // 1 リクエストごとに使い捨てのサーバーとトランスポートを作る
    const server = options.serverFactory();
    const transport = new StreamableHTTPServerTransport({
      // undefined がステートレスの宣言。セッション ID を発行せず、検証もしない
      sessionIdGenerator: undefined,
    });

    // 後始末は「応答が閉じたとき」に行う。handleRequest の直後に閉じると
    // SSE の書き込み中に切ってしまうことがある
    res.on("close", () => {
      void transport.close();
      void server.close();
    });

    await server.connect(transport);
    await transport.handleRequest(req, res, parsed.value);
  }

  return (req, res) => {
    dispatch(req, res).catch((error: unknown) => {
      log(`未処理の例外: ${error instanceof Error ? error.message : String(error)}`);
      if (res.headersSent) {
        res.end();
      } else {
        sendError(res, 500, -32603, "サーバー内部エラーです。");
      }
    });
  };
}

export async function startStatelessServer(
  options: StatelessOptions,
): Promise<{ httpServer: http.Server; close: () => Promise<void> }> {
  const host = options.host ?? DEFAULT_HOST;
  const port = options.port ?? DEFAULT_PORT;
  const httpServer = http.createServer(createStatelessListener(options));

  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error): void => reject(error);
    httpServer.once("error", onError);
    httpServer.listen(port, host, () => {
      httpServer.removeListener("error", onError);
      resolve();
    });
  });

  return {
    httpServer,
    close: async () => {
      httpServer.closeAllConnections();
      await new Promise<void>((resolve) => {
        httpServer.close(() => resolve());
      });
    },
  };
}
