/**
 * 比較用：低水準 Server クラスで list_members だけを実装したもの
 *
 * McpServer が何を代行しているのかを体感するためのコードです。
 * 実務では McpServer を使ってください（このファイルは学習用）。
 *
 * 表示の整形は本文のサーバーと同じ結果にしたいので、あえて同じ実装をここにも置いています。
 * こうすることで、このファイルが create-server.ts（McpServer 側）に依存しないことを示せます。
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
  type CallToolResult,
  type ListToolsResult,
} from "@modelcontextprotocol/sdk/types.js";

import { listMembers, type Member } from "./data.js";

const TEAMS = ["platform", "data"] as const;

export function createLowLevelServer(): Server {
  // ① ケイパビリティを自分で宣言する（McpServer は registerTool から自動で判断していた）
  const server = new Server(
    { name: "team-dashboard-lowlevel", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  // ② tools/list のレスポンスを自分で組み立てる。JSON Schema も手書き
  server.setRequestHandler(
    ListToolsRequestSchema,
    async (): Promise<ListToolsResult> => ({
      tools: [
        {
          name: "list_members",
          title: "メンバー一覧",
          description:
            "チームに所属するメンバーの一覧（ID・氏名・チーム・週の稼働可能時間）を返します。" +
            "稼働時間を集計する前に、有効なメンバー ID を確認する用途で使ってください。",
          inputSchema: {
            type: "object",
            properties: {
              team: {
                type: "string",
                enum: [...TEAMS],
                description: "特定のチームだけに絞る場合に指定します。省略すると全員を返します。",
              },
            },
          },
        },
      ],
    }),
  );

  // ③ tools/call のディスパッチも自分で書く
  server.setRequestHandler(
    CallToolRequestSchema,
    async (request): Promise<CallToolResult> => {
      if (request.params.name !== "list_members") {
        // ④ 未知のツール名への応答も自分の責任
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
      }

      // ⑤ 引数は unknown で届く。型の確認も列挙の確認も手作業
      const args = request.params.arguments ?? {};
      const team = args["team"];
      if (team !== undefined && typeof team !== "string") {
        throw new McpError(ErrorCode.InvalidParams, "team は文字列で指定してください");
      }
      if (team !== undefined && !TEAMS.includes(team as (typeof TEAMS)[number])) {
        throw new McpError(
          ErrorCode.InvalidParams,
          `team は ${TEAMS.join(" / ")} のいずれかを指定してください`,
        );
      }

      return { content: [{ type: "text", text: formatMembers(listMembers(team)) }] };
    },
  );

  return server;
}

function formatMembers(found: Member[]): string {
  if (found.length === 0) {
    return "該当するメンバーはいません。";
  }
  const lines = found.map(
    (member) =>
      `- ${member.id} ${member.name}（${member.team} / 週 ${member.weeklyCapacityHours} 時間）`,
  );
  return [`メンバー ${found.length} 名`, ...lines].join("\n");
}
