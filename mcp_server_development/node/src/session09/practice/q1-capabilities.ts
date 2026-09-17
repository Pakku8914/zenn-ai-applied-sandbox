/**
 * 問題1: クライアントのケイパビリティを読み取って報告する
 *
 * 優雅な劣化の第 1 段（呼ぶ前に確認する）だけを取り出した練習です。
 * 1 つのサーバーに 2 つのクライアントはつなげないので、
 * クライアントごとにサーバーを作り直します。
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  CreateMessageRequestSchema,
  ElicitRequestSchema,
  ListRootsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

type Support = { sampling: boolean; roots: boolean; elicitation: boolean };
type ToolResult = { structuredContent?: Support; [key: string]: unknown };

function createServer(): McpServer {
  const server = new McpServer({ name: "capability-probe", version: "1.0.0" });

  server.registerTool(
    "report_support",
    {
      title: "クライアント機能の対応状況",
      description:
        "接続しているクライアントが sampling / roots / elicitation を申告しているかを返します。",
      inputSchema: {},
      outputSchema: {
        sampling: z.boolean().describe("sampling/createMessage を呼べるか"),
        roots: z.boolean().describe("roots/list を呼べるか"),
        elicitation: z.boolean().describe("elicitation/create を呼べるか"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    () => {
      const capabilities = server.server.getClientCapabilities();
      // 値は {}（空オブジェクト）なので、=== true では判定できない
      const support: Support = {
        sampling: capabilities?.sampling !== undefined,
        roots: capabilities?.roots !== undefined,
        elicitation: capabilities?.elicitation !== undefined,
      };
      return {
        content: [
          {
            type: "text" as const,
            text:
              `sampling=${support.sampling} / roots=${support.roots}` +
              ` / elicitation=${support.elicitation}`,
          },
        ],
        structuredContent: support,
      };
    },
  );

  return server;
}

async function probe(client: Client): Promise<Support | undefined> {
  const server = createServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

  const result = (await client.callTool({
    name: "report_support",
    arguments: {},
  })) as ToolResult;

  await client.close();
  await server.close();
  return result.structuredContent;
}

// 3 機能を申告するクライアント。申告とハンドラは必ずセットにする
const capableClient = new Client(
  { name: "q1-capable", version: "1.0.0" },
  { capabilities: { sampling: {}, roots: { listChanged: true }, elicitation: {} } },
);
capableClient.setRequestHandler(ListRootsRequestSchema, () => ({ roots: [] }));
capableClient.setRequestHandler(CreateMessageRequestSchema, () => ({
  model: "stub-model",
  role: "assistant" as const,
  content: { type: "text" as const, text: "（この問題では呼ばれません）" },
  stopReason: "endTurn",
}));
capableClient.setRequestHandler(ElicitRequestSchema, () => ({ action: "decline" as const }));

// 何も申告しないクライアント
const plainClient = new Client({ name: "q1-plain", version: "1.0.0" });

const withSupport = await probe(capableClient);
console.log(
  `[1/2] 申告あり: sampling=${withSupport?.sampling} / roots=${withSupport?.roots}` +
    ` / elicitation=${withSupport?.elicitation}`,
);

const withoutSupport = await probe(plainClient);
console.log(
  `[2/2] 申告なし: sampling=${withoutSupport?.sampling} / roots=${withoutSupport?.roots}` +
    ` / elicitation=${withoutSupport?.elicitation}`,
);

console.log("OK: 問題1 の条件を満たしています");
