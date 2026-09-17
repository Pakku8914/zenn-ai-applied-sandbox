/**
 * わざと契約を壊した複製（問題4-a の解答）
 *
 * fixture-server.ts の echo_text を複製し、引数名 text を message に変えただけです。
 *
 * ★ 本番のサーバーを直接壊して確認しないこと。「あとで戻す」つもりの変更が
 *   そのままコミットされる事故は現実に起きます。壊した複製を用意すれば、
 *   「スナップショットが破壊的変更を検出できること」自体をテストとして残せます。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function createBrokenFixtureServer(): McpServer {
  const server = new McpServer({ name: "session13-fixture", version: "1.0.0" });

  server.registerTool(
    "echo_text",
    {
      title: "テキストのエコー",
      description:
        "受け取ったテキストを指定回数だけ繰り返して返します。テストの土台を確かめるためのツールです。",
      inputSchema: {
        // ❌ ここだけが違う。text → message（引数名の改名 ＝ 破壊的変更）
        message: z.string().min(1).max(100).describe("繰り返す対象のテキスト（1〜100 文字）"),
        count: z.number().int().min(1).max(5).optional().describe("繰り返す回数（1〜5、既定 1）"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    ({ message, count }) => ({
      content: [
        {
          type: "text" as const,
          text: Array.from({ length: count ?? 1 }, () => message).join("\n"),
        },
      ],
    }),
  );

  return server;
}
