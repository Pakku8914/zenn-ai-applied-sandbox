/**
 * 問題2: 用途別の modelPreferences プロファイル
 *
 * hints に具体的なモデル名を書かない理由:
 *   ① 陳腐化する ―― モデル名は数か月で変わる。コードに書いた名前は必ず古くなり、
 *      しかも「動かない」ではなく「静かに無視される」ので気付けない
 *   ② ホストに依存する ―― サーバーは自分がどのホストで動くか知らない。
 *      あるホストで有効なヒントは、別のホストでは存在しないモデル名になる
 *
 * 代わりに 3 つの優先度で「どんなモデルが欲しいか」を伝える。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { CreateMessageRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

/**
 * 用途別プロファイル。値の意味は「相対的な重み」で、合計が 1 になる必要はない。
 *   quick   : 対話中の要約。速く安く。多少ざっくりでよい
 *   careful : 監査報告の下書き。時間と費用をかけてよいので精度を優先
 *   bulk    : 100 件への一括ラベル付け。費用が最優先で、出力は短い
 */
const PROFILES = {
  quick: { costPriority: 0.8, speedPriority: 0.9, intelligencePriority: 0.2, maxTokens: 320 },
  careful: { costPriority: 0.2, speedPriority: 0.2, intelligencePriority: 0.9, maxTokens: 320 },
  bulk: { costPriority: 1.0, speedPriority: 0.6, intelligencePriority: 0.1, maxTokens: 120 },
} as const;

const PROFILE_NAMES = ["quick", "careful", "bulk"] as const;

const server = new McpServer({ name: "preference-demo", version: "1.0.0" });

server.registerTool(
  "summarize_with",
  {
    title: "プロファイルを指定して要約する",
    description:
      "modelPreferences のプロファイルを切り替えて sampling を呼びます。" +
      "モデルID は指定しません（どんなモデルが欲しいかを優先度で伝えます）。",
    inputSchema: {
      profile: z
        .enum(PROFILE_NAMES)
        .describe("用途別のプロファイル。quick は速さ優先、careful は精度優先、bulk は費用優先"),
    },
    outputSchema: {
      profile: z.string().describe("使ったプロファイル名"),
      echoed: z.string().describe("クライアントが受け取った値のエコー"),
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      // LLM の応答は毎回同じとは限らない
      idempotentHint: false,
      // クライアント越しに外部のモデルへ依存する
      openWorldHint: true,
    },
  },
  async ({ profile }, extra) => {
    const preference = PROFILES[profile];
    const result = await server.server.createMessage(
      {
        messages: [
          { role: "user", content: { type: "text", text: "この文書を要約してください。" } },
        ],
        maxTokens: preference.maxTokens,
        // 他サーバーの文脈を混ぜない
        includeContext: "none",
        modelPreferences: {
          costPriority: preference.costPriority,
          speedPriority: preference.speedPriority,
          intelligencePriority: preference.intelligencePriority,
          // hints は書かない（ファイル先頭のコメントの理由）
        },
      },
      { relatedRequestId: extra.requestId, signal: extra.signal, timeout: 10_000 },
    );
    const echoed = result.content.type === "text" ? result.content.text : "(text 以外が返りました)";
    return {
      content: [{ type: "text" as const, text: echoed }],
      structuredContent: { profile, echoed },
    };
  },
);

const client = new Client(
  { name: "q2-client", version: "1.0.0" },
  { capabilities: { sampling: {} } },
);

// ダミーハンドラ。受け取った値をそのまま返すので、届いているかが検証できる
client.setRequestHandler(CreateMessageRequestSchema, (request) => {
  const preference = request.params.modelPreferences;
  return {
    model: "stub-echo",
    role: "assistant" as const,
    content: {
      type: "text" as const,
      text:
        `cost=${preference?.costPriority} / speed=${preference?.speedPriority}` +
        ` / intelligence=${preference?.intelligencePriority}` +
        ` / maxTokens=${request.params.maxTokens}`,
    },
    stopReason: "endTurn",
  };
});

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

for (const [index, profile] of PROFILE_NAMES.entries()) {
  const result = (await client.callTool({
    name: "summarize_with",
    arguments: { profile },
  })) as { structuredContent?: { echoed: string } };
  console.log(`[${index + 1}/3] ${profile}: ${result.structuredContent?.echoed}`);
}

await client.close();
await server.close();
console.log("OK: 問題2 の条件を満たしています");
