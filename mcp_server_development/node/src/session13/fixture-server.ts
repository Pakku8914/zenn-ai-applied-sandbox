/**
 * テスト専用のサーバー（fixture）
 *
 * 異常系・タイムアウト・キャンセルを確かめるには「わざと失敗する／わざと遅い」ツールが
 * 必要です。本番のサーバーにそういうツールを足すと配布物に混ざるので、テスト用に分けます。
 *
 * ツールだけを 3 本公開し、リソースとプロンプトは登録しません。
 * → resources 系のメソッドが「宣言していないケイパビリティ」になり、
 *   本物の JSON-RPC エラー（-32601）を観測できます。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export const FIXTURE_NAME = "session13-fixture";
export const FIXTURE_VERSION = "1.0.0";

/** キャンセルが届いて実際に処理を止めたことを記録する（テストから読む） */
const cancelled: string[] = [];

export function cancelledTasks(): readonly string[] {
  return cancelled;
}

export function resetCancelledTasks(): void {
  cancelled.length = 0;
}

export function createFixtureServer(): McpServer {
  const server = new McpServer({ name: FIXTURE_NAME, version: FIXTURE_VERSION });

  server.registerTool(
    "echo_text",
    {
      title: "テキストのエコー",
      description:
        "受け取ったテキストを指定回数だけ繰り返して返します。テストの土台を確かめるためのツールです。",
      inputSchema: {
        text: z.string().min(1).max(100).describe("繰り返す対象のテキスト（1〜100 文字）"),
        count: z.number().int().min(1).max(5).optional().describe("繰り返す回数（1〜5、既定 1）"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    ({ text, count }) => ({
      content: [
        {
          type: "text" as const,
          text: Array.from({ length: count ?? 1 }, () => text).join("\n"),
        },
      ],
    }),
  );

  server.registerTool(
    "fail_always",
    {
      title: "必ず失敗する処理",
      description: "ツール実行層の失敗（isError）を観測するためのツールです。常に失敗します。",
      inputSchema: {
        reason: z.string().min(1).max(50).describe("失敗理由として返す文字列"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    ({ reason }) => ({
      content: [{ type: "text" as const, text: `[failed] ${reason}` }],
      isError: true,
    }),
  );

  server.registerTool(
    "slow_task",
    {
      title: "時間のかかる処理",
      description:
        "指定したミリ秒だけ待ってから終わります。キャンセルとタイムアウトの検証に使います。",
      inputSchema: {
        taskId: z.string().min(1).max(50).describe("記録用のタスク識別子"),
        ms: z.number().int().min(0).max(10_000).describe("待つ時間（ミリ秒）"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async ({ taskId, ms }, extra) => {
      const startedAt = Date.now();
      while (Date.now() - startedAt < ms) {
        // ★ キャンセルは「受け取る」だけでは意味がない。実際に処理を止める（セッション8）
        if (extra.signal.aborted) {
          cancelled.push(taskId);
          return {
            content: [{ type: "text" as const, text: `${taskId} を中断しました` }],
            isError: true,
          };
        }
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      return { content: [{ type: "text" as const, text: `${taskId} を ${ms}ms で完了しました` }] };
    },
  );

  return server;
}
