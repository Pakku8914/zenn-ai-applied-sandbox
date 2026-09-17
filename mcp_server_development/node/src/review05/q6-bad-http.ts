/**
 * ⚠️ 意図的に危険なコードです。手本にしないでください。⚠️
 *
 * 横断復習5 の問題6「この公開手順の何が危ないかを挙げる」の出題文そのものです。
 * 掲載のみで、実行も import もしません（起動すると本当に穴の空いたサーバーが
 * 0.0.0.0 で待ち受けます）。
 *
 * 仕込んである欠陥（解答は「セッション横断復習5：解答と解説」にあります）:
 *   - Authorization ヘッダーの「有無」しか見ていない。署名・aud・exp を検証して
 *     いないため、でたらめな文字列を 1 つ付けるだけで通る
 *   - 0.0.0.0 で待ち受けている。127.0.0.1 に絞らないと LAN の他端末から届く
 *   - Origin を検証していないため DNS リバインディングを防げない
 *   - 例外のスタックトレースをそのまま応答本文に入れている
 *   - セッションを Map に入れっぱなしで破棄していない
 */
import http from "node:http";
import { randomUUID } from "node:crypto";

import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createGateServer } from "./gate-server.js";

const sessions = new Map<string, StreamableHTTPServerTransport>();

const httpServer = http.createServer(async (req, res) => {
  const token = req.headers.authorization;
  if (token === undefined) {
    res.writeHead(401).end("unauthorized");
    return;
  }

  const sessionId = req.headers["mcp-session-id"];
  let transport = typeof sessionId === "string" ? sessions.get(sessionId) : undefined;
  if (transport === undefined) {
    const id = randomUUID();
    transport = new StreamableHTTPServerTransport({ sessionIdGenerator: () => id });
    sessions.set(id, transport);
    await createGateServer({ scopes: ["requests:read", "requests:approve"] }).connect(transport);
  }

  try {
    await transport.handleRequest(req, res);
  } catch (error) {
    res.writeHead(500).end(String(error instanceof Error ? error.stack : error));
  }
});

httpServer.listen(3939, "0.0.0.0", () => {
  console.log("listening on 0.0.0.0:3939");
});
