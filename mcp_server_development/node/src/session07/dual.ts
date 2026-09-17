/**
 * 同じサーバー定義を stdio と Streamable HTTP のどちらにも載せられるエントリーポイント
 *
 *   MCP_TRANSPORT=stdio（既定） / http
 *
 * 起動（stdio）:
 *   docker compose exec node npx tsx src/session07/dual.ts
 * 起動（HTTP）:
 *   docker compose exec -d -e MCP_TRANSPORT=http node sh -c 'npx tsx src/session07/dual.ts > /tmp/http.log 2>&1'
 *
 * ログは「どちらの経路でも」stderr に出します。stdio 経路では stdout が
 * JSON-RPC の通信路そのものなので、分岐のどこかに console.log が 1 つ混ざるだけで
 * 電文が壊れます。行き先を分岐させないのが最も安全です。
 */
import { unlinkSync, writeFileSync } from "node:fs";

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { resolveDocsRoot } from "../mid01/config.js";
import { createDocSearchServer } from "../mid01/create-server.js";
import { DEFAULT_HOST, DEFAULT_PORT, startHttpServer } from "./http-server.js";
import { resolveTrustPolicy } from "./origin.js";

const PID_FILE = "/tmp/mcp-http.pid";
const transportName = process.env["MCP_TRANSPORT"] ?? "stdio";
const docsRoot = resolveDocsRoot([]);

function note(message: string): void {
  console.error(`[docsearch] ${message}`);
}

if (transportName === "stdio") {
  // 既定は stdio。事故の方向を安全側へ倒す（HTTP はネットワークに口を開けるので明示させる）
  const server = createDocSearchServer({ docsRoot });
  await server.connect(new StdioServerTransport());
  note(`stdio でリクエストを待機しています（docsRoot=${docsRoot}）`);
  // 終了処理は不要。標準入力の EOF で SDK が自分を閉じ、プロセスが終わる
} else if (transportName === "http") {
  const host = process.env["MCP_HTTP_HOST"] ?? DEFAULT_HOST;
  const port = Number(process.env["MCP_HTTP_PORT"] ?? String(DEFAULT_PORT));
  const running = await startHttpServer({
    serverFactory: () => createDocSearchServer({ docsRoot }),
    host,
    port,
    trust: resolveTrustPolicy(process.env, port),
  });

  writeFileSync(PID_FILE, `${process.pid}\n`, "utf8");
  note(`Streamable HTTP で待ち受けています: http://${host}:${port}${running.endpoint}`);
  note(`PID ${process.pid}。停止するには kill ${process.pid}`);

  // HTTP 経路だけ終了処理が必要（ホストが面倒を見てくれないので自分で閉じる）
  process.on("SIGTERM", () => {
    void (async () => {
      note("SIGTERM を受け取りました。セッションを閉じて終了します");
      await running.close();
      try {
        unlinkSync(PID_FILE);
      } catch {
        // すでに消えていてもよい
      }
      process.exit(0);
    })();
  });
} else {
  // 黙って stdio にフォールバックしない。「HTTP で立てたつもりが stdio だった」は
  // 原因調査が難しく、しかも「動いているつもり」で放置される事故になる
  note(`MCP_TRANSPORT に不明な値が指定されました: ${transportName}（stdio / http のいずれか）`);
  process.exit(1);
}
