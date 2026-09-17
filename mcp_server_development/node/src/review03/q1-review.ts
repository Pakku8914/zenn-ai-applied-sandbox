  import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

  import { createDocSearchLiteServer } from "./create-server-lite.js";

  console.log("[docsearch] サーバーを起動します");

  const server = createDocSearchLiteServer();
  await server.connect(new StdioServerTransport());

  // 稼働状況を 1 秒ごとに出す
  setInterval(() => {
    console.log(JSON.stringify({ uptimeSec: Math.round(process.uptime()) }));
  }, 1000);

  // ツール呼び出しの記録（呼び出し箇所は省略）
  export function logCall(name: string, args: unknown): void {
    console.log(JSON.stringify({ tool: name, args }, null, 2));
  }

  process.on("SIGTERM", () => {
    console.log("[docsearch] 終了します");
    process.exit(0);
  });
