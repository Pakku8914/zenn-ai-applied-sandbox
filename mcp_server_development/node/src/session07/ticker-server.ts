  /**
   * 再開可能性を実験するための最小サーバー
   *
   * 一定間隔でツールの有効・無効を切り替えます。McpServer は切り替えのたびに
   * notifications/tools/list_changed を送るので、GET のストリームにイベントが流れます。
   * docsearch は通知を 1 つも送らないので、実験にはこのサーバーを使います。
   */
  import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

  export function createTickerServer(intervalMs = 1000): McpServer {
    const server = new McpServer({ name: "ticker", version: "0.1.0" });

    const maintenance = server.registerTool(
      "maintenance_window",
      {
        title: "メンテナンス予定の確認",
        description: "実験用のツールです。一定間隔で有効・無効が切り替わります。",
        annotations: {
          readOnlyHint: true,
          destructiveHint: false,
          idempotentHint: true,
          openWorldHint: false,
        },
      },
      async () => ({
        content: [{ type: "text" as const, text: "メンテナンスの予定はありません。" }],
      }),
    );

    let enabled = true;
    const timer = setInterval(() => {
      enabled = !enabled;
      try {
        if (enabled) {
          maintenance.enable();
        } else {
          maintenance.disable();
        }
      } catch (error) {
        console.error(
          `[ticker] 通知の送信に失敗しました: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }, intervalMs);

    // タイマーがプロセスを生かし続けないようにする（stdio の罠5 と同じ話）
    timer.unref();
    server.server.onclose = () => clearInterval(timer);

    return server;
  }
