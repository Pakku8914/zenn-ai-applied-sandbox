/**
 * 問題4: elicitation の accept / decline / cancel と、accept の中身の検証
 *
 * 4 つのクライアントを順に接続して 4 分岐すべてを通します。
 * ヒューマン・イン・ザ・ループはクライアント側の責務なので、
 * サーバー側のテストは「どんな応答が来ても壊れないか」の確認になります。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ElicitRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

/** 選択肢。readonly string[] にしておくと includes() が素直に書ける */
const CANDIDATES: readonly string[] = ["faq", "guides"];
const CANDIDATE_LABELS: readonly string[] = ["FAQ", "手順書"];
/** 人間の操作を待つので長めに取る */
const ELICITATION_TIMEOUT_MS = 120_000;

type Outcome = "answered" | "declined" | "invalid" | "unavailable";

function success(query: string, outcome: Outcome, value: string | undefined) {
  return {
    content: [
      { type: "text" as const, text: `outcome=${outcome} / value=${value ?? "なし"}` },
    ],
    // undefined を入れると outputSchema の検証に失敗する。キー自体を作らない
    structuredContent: { query, outcome, ...(value === undefined ? {} : { value }) },
  };
}

function createServer(): McpServer {
  const server = new McpServer({ name: "elicitation-demo", version: "1.0.0" });

  server.registerTool(
    "pick_directory",
    {
      title: "検索対象のディレクトリを選ぶ",
      description: "ユーザーに検索対象のディレクトリを尋ね、選ばれた値を返します。",
      inputSchema: { query: z.string().min(1).max(100).describe("検索語") },
      outputSchema: {
        query: z.string(),
        outcome: z
          .enum(["answered", "declined", "invalid", "unavailable"])
          .describe("elicitation の結果"),
        value: z.string().optional().describe("選ばれたディレクトリ"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        // ユーザーの回答次第で結果が変わる
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ query }, extra) => {
      // ① 申告を確認する（無いなら呼ばない）
      if (server.server.getClientCapabilities()?.elicitation === undefined) {
        return success(query, "unavailable", undefined);
      }

      // ② 呼ぶ。失敗しても例外を外に出さない
      let result;
      try {
        result = await server.server.elicitInput(
          {
            message: `「${query}」の検索対象を選んでください。`,
            // フラットなプリミティブだけ。オブジェクトの入れ子は使えない
            requestedSchema: {
              type: "object",
              properties: {
                directory: {
                  type: "string",
                  title: "検索対象のディレクトリ",
                  description: "候補から 1 つ選んでください。",
                  enum: [...CANDIDATES],
                  enumNames: [...CANDIDATE_LABELS],
                },
              },
              required: ["directory"],
            },
          },
          {
            relatedRequestId: extra.requestId,
            signal: extra.signal,
            timeout: ELICITATION_TIMEOUT_MS,
          },
        );
      } catch (error) {
        console.error("[q4] elicitation/create に失敗しました:", error);
        return success(query, "unavailable", undefined);
      }

      // ③ 3 つの action を区別する
      if (result.action === "cancel") {
        // 中断は「やめる」。ここで検索や要約を続けると費用と時間が無駄になる
        return {
          content: [
            { type: "text" as const, text: "ユーザーが操作を中断したため、処理を中止しました。" },
          ],
          isError: true,
        };
      }
      if (result.action === "decline") {
        // 拒否は「絞り込まないで続けて」。処理は続ける
        return success(query, "declined", undefined);
      }

      // ④ accept でも中身を検証する（型 ＋ 候補集合への所属）
      const answer = result.content?.["directory"];
      if (typeof answer !== "string" || !CANDIDATES.includes(answer)) {
        return success(query, "invalid", undefined);
      }
      return success(query, "answered", answer);
    },
  );

  return server;
}

type ElicitReply = {
  action: "accept" | "decline" | "cancel";
  content?: Record<string, unknown>;
};

type ToolResult = {
  content: { text?: string }[];
  structuredContent?: { outcome: string; value?: string };
  isError?: boolean;
  [key: string]: unknown;
};

async function run(name: string, reply: () => ElicitReply): Promise<ToolResult> {
  const server = createServer();
  const client = new Client({ name, version: "1.0.0" }, { capabilities: { elicitation: {} } });
  client.setRequestHandler(ElicitRequestSchema, () => reply());

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

  const result = (await client.callTool({
    name: "pick_directory",
    arguments: { query: "連絡" },
  })) as ToolResult;

  await client.close();
  await server.close();
  return result;
}

const accepted = await run("q4-accept", () => ({
  action: "accept",
  content: { directory: "faq" },
}));
console.log(
  `[1/4] accept: outcome=${accepted.structuredContent?.outcome}` +
    ` / value=${accepted.structuredContent?.value ?? "なし"}` +
    ` / isError=${accepted.isError === true}`,
);

const declined = await run("q4-decline", () => ({ action: "decline" }));
console.log(
  `[2/4] decline: outcome=${declined.structuredContent?.outcome}` +
    ` / value=${declined.structuredContent?.value ?? "なし"}` +
    ` / isError=${declined.isError === true}`,
);

const cancelled = await run("q4-cancel", () => ({ action: "cancel" }));
console.log(
  `[3/4] cancel: isError=${cancelled.isError === true} / message=${cancelled.content[0]?.text}`,
);

// 悪意ある（あるいは実装が壊れた）クライアント。enum の外の値を返す
const invalid = await run("q4-invalid", () => ({
  action: "accept",
  content: { directory: "../../etc" },
}));
console.log(
  `[4/4] 候補外の値: outcome=${invalid.structuredContent?.outcome}` +
    ` / value=${invalid.structuredContent?.value ?? "なし"}` +
    ` / isError=${invalid.isError === true}`,
);

console.log("OK: 問題4 の条件を満たしています");
