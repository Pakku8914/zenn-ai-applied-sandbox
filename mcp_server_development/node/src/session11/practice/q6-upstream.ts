/**
 * 問題6 の解答：外部システムの障害と権限の失敗を書き分ける
 *
 * 実行： docker compose exec node npx tsx src/session11/practice/q6-upstream.ts
 *
 * 同じ isError: true でも、retryable が true のものと false のものがあります。
 * モデルの次の行動を決めるのはこのフラグと文面です。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { leaksInternalDetail, toolFailureWith, type ToolFailure } from "../errors.js";
import { ROOMS, createAvailabilityApi, type AvailabilityApi } from "./rooms.js";

const REQUIRED_SCOPE = "rooms:read";
const RETRY_AFTER_SECONDS = 3;

export type AvailabilityServerOptions = {
  api?: AvailabilityApi;
  grantedScopes?: readonly string[];
};

export function createAvailabilityServer(options: AvailabilityServerOptions = {}): McpServer {
  const api = options.api ?? createAvailabilityApi();
  const granted = options.grantedScopes ?? [REQUIRED_SCOPE];
  const server = new McpServer({ name: "rooms-availability", version: "1.0.0" });

  server.registerTool(
    "check_availability",
    {
      title: "会議室の空き時間を調べる",
      description:
        "指定した会議室と日付の空き開始時刻を返します。予約の作成・変更は行いません。" +
        "設備管理システムに問い合わせるため、外部システムの障害で失敗することがあります" +
        "（その場合は error.retryable が true になり、待ってから再試行できます）。",
      inputSchema: {
        roomId: z.enum(ROOMS).describe("会議室。この 3 室以外は存在しません"),
        date: z
          .string()
          .regex(/^\d{4}-\d{2}-\d{2}$/)
          .describe("調べたい日付（YYYY-MM-DD）"),
      },
      outputSchema: {
        roomId: z.string(),
        date: z.string(),
        freeHours: z.array(z.number().int()).describe("空いている開始時刻（時）"),
        error: z
          .object({
            code: z.string(),
            retryable: z.boolean(),
            retryAfterSeconds: z.number().int().optional(),
          })
          .optional(),
      },
      annotations: {
        readOnlyHint: true,
        idempotentHint: true,
        // 外部システムに問い合わせるので openWorldHint は true
        openWorldHint: true,
      },
    },
    async ({ roomId, date }) => {
      /** 失敗しても outputSchema の形を保つための土台 */
      const base = { roomId, date, freeHours: [] as number[] };

      // 権限の検査は外部呼び出しの前に行う（無駄な外部アクセスを避ける）
      if (!granted.includes(REQUIRED_SCOPE)) {
        const failure: ToolFailure = {
          code: "forbidden",
          what: `この操作には権限 ${REQUIRED_SCOPE} が必要ですが、現在の接続には付与されていません。`,
          next: `付与されている権限は ${granted.length === 0 ? "なし" : granted.join(", ")} です。権限の追加はユーザーから管理者に依頼してください。同じ引数で呼び直しても結果は変わりません。`,
          retryable: false,
        };
        return toolFailureWith(failure, base);
      }

      try {
        const { freeHours } = await api.check(roomId, date);
        return {
          content: [
            {
              type: "text",
              text:
                `${roomId} / ${date} の空き開始時刻: ${freeHours.join(", ")}（時）\n` +
                "予約するには Web 画面から操作してください（このサーバーは予約を作成しません）。",
            },
          ],
          structuredContent: { roomId, date, freeHours },
        };
      } catch (error) {
        // 詳細は stderr にだけ出す。内部 IP・パス・トークンは返さない
        console.error(`[upstream] availability check failed for ${roomId} ${date}:`, error);
        const failure: ToolFailure = {
          code: "upstream_unavailable",
          what: "設備管理システムに接続できず、空き時間を取得できませんでした。予約の作成や変更は行っていません。",
          next: `${RETRY_AFTER_SECONDS} 秒ほど待って同じ引数で呼び直してください。数分続く場合は、空き状況を Web 画面で確認するようユーザーに案内してください。`,
          retryable: true,
          retryAfterSeconds: RETRY_AFTER_SECONDS,
        };
        return toolFailureWith(failure, base);
      }
    },
  );

  return server;
}

// ── 検証 ────────────────────────────────────────────────────────────────
async function connect(server: McpServer, label: string): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: `practice-q6-${label}`, version: "1.0.0" });
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return client;
}

type Result = { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown };

function text(result: Result): string {
  return (result.content as Array<{ text?: string }> | undefined)?.[0]?.text ?? "";
}

function structuredError(result: Result): { code?: string; retryable?: boolean; retryAfterSeconds?: number } | undefined {
  return (result.structuredContent as { error?: { code?: string; retryable?: boolean; retryAfterSeconds?: number } } | undefined)
    ?.error;
}

const args = { roomId: "room-b", date: "2026-09-01" };

// 1 回だけ失敗する外部 API
const flaky = await connect(
  createAvailabilityServer({ api: createAvailabilityApi({ failures: 1 }) }),
  "flaky",
);
const failed = await flaky.callTool({ name: "check_availability", arguments: args });
const failedError = structuredError(failed);
console.log(
  `[1/4] 外部障害: code=${failedError?.code} retryable=${failedError?.retryable} ` +
    `retryAfter=${failedError?.retryAfterSeconds} ` +
    `露出=${leaksInternalDetail(text(failed)) ? "あり" : "なし"}`,
);

const retried = await flaky.callTool({ name: "check_availability", arguments: args });
const retriedOut = retried.structuredContent as { freeHours: number[] };
console.log(
  `[2/4] 再試行で成功: isError=${retried.isError === true} freeHours=${retriedOut.freeHours.join(",")}`,
);

// 権限を与えていない接続
const noScope = await connect(createAvailabilityServer({ grantedScopes: [] }), "noscope");
const forbidden = await noScope.callTool({ name: "check_availability", arguments: args });
const forbiddenError = structuredError(forbidden);
console.log(
  `[3/4] 権限なし: code=${forbiddenError?.code} retryable=${forbiddenError?.retryable}`,
);

console.log(
  `[4/4] 構造化エラーが両方で返る=${failedError !== undefined && forbiddenError !== undefined}`,
);

await flaky.close();
await noScope.close();
