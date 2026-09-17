/**
 * 気象観測データ MCP サーバー（Good 実装）
 *
 * この 1 ファイルに、本章で扱う 5 つの機構が入っています。
 *   - ページネーション   : list_observations
 *   - 進捗通知           : aggregate_observations
 *   - キャンセル         : aggregate_observations
 *   - ロギング           : logging/setLevel + notifications/message
 *   - list_changed       : enable_experimental_metrics
 *
 * セッション7 と同じく、トランスポートへの接続はここでは行いません（server.ts の役割）。
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  SetLevelRequestSchema,
  type ServerNotification,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  accumulate,
  decodeCursor,
  encodeCursor,
  findStartIndex,
  getObservations,
  summarize,
  toPublic,
  TOTAL_STEPS,
  type StationAccumulator,
} from "./observations.js";

/** MCP のログレベル。左が最も詳細で、右が最も重大（syslog 準拠の 8 段階） */
const LEVEL_ORDER = [
  "debug", "info", "notice", "warning", "error", "critical", "alert", "emergency",
] as const;
type LogLevel = (typeof LEVEL_ORDER)[number];

/** キャンセルが本当に効いたかを外から確認するための実行記録 */
export type RunReport = {
  tool: string;
  totalSteps: number;
  executedSteps: number;
  finished: boolean;
  cancelled: boolean;
};

/**
 * AbortSignal を見張る sleep。
 * キャンセルされたら残り時間を待たずに例外を投げるので、反応が速くなります。
 */
function sleepOrAbort(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("キャンセル済みのため処理を開始しません"));
      return;
    }
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(new Error("キャンセル通知を受け取ったため中断しました"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function createServer(): McpServer {
  const server = new McpServer(
    { name: "weather-observations", version: "1.0.0" },
    // logging ケイパビリティは自分で宣言する。宣言しないと
    // notifications/message を送ろうとした時点で SDK が例外を投げます
    { capabilities: { logging: {} } },
  );

  let currentLevel: LogLevel = "info";
  let lastRun: RunReport = {
    tool: "aggregate_observations",
    totalSteps: TOTAL_STEPS,
    executedSteps: 0,
    finished: false,
    cancelled: false,
  };

  // logging/setLevel は SDK が自動処理しないため、自分でハンドラを登録します
  server.server.setRequestHandler(SetLevelRequestSchema, async (request) => {
    currentLevel = request.params.level as LogLevel;
    console.error(`[log] レベルを ${currentLevel} に変更しました`);
    return {}; // 空の結果を返すのが仕様
  });

  const isEnabled = (level: LogLevel): boolean =>
    LEVEL_ORDER.indexOf(level) >= LEVEL_ORDER.indexOf(currentLevel);

  /** クライアントへログを送る。レベルで絞り、送信失敗は本流を止めない */
  const sendLog = async (
    send: (notification: ServerNotification) => Promise<void>,
    level: LogLevel,
    message: string,
    detail: Record<string, unknown> = {},
  ): Promise<void> => {
    if (!isEnabled(level)) return;
    try {
      await send({
        method: "notifications/message",
        params: { level, logger: "weather", data: { message, ...detail } },
      });
    } catch (error) {
      console.error("[log] notifications/message の送信に失敗しました:", error);
    }
  };

  // ---------------- ページネーション ----------------
  server.registerTool(
    "list_observations",
    {
      title: "観測レコードの一覧",
      description:
        "気象観測レコードを観測時刻の昇順で返します。1 回の呼び出しで返す件数には上限があるため、" +
        "続きを取得するにはレスポンスの nextCursor をそのまま cursor に渡してください。" +
        "cursor の中身は解釈しないでください（形式は予告なく変わります）。",
      inputSchema: {
        cursor: z
          .string()
          .optional()
          .describe("前回のレスポンスの nextCursor をそのまま渡します。省略すると先頭から返します"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(200)
          .default(50)
          .describe("1 回で返す最大件数（1〜200、既定 50）"),
        stationId: z.string().optional().describe("観測所 ID で絞り込みます（例: st-01）"),
      },
      outputSchema: {
        observations: z.array(
          z.object({
            id: z.string(),
            stationId: z.string(),
            observedAt: z.string(),
            temperatureC: z.number(),
            humidityPct: z.number(),
            precipitationMm: z.number(),
          }),
        ),
        returned: z.number().int(),
        nextCursor: z.string().optional(),
        hasMore: z.boolean(),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ cursor, limit, stationId }) => {
      const all = getObservations();
      const rows = stationId === undefined ? all : all.filter((row) => row.stationId === stationId);

      let start = 0;
      if (cursor !== undefined) {
        try {
          start = findStartIndex(rows, decodeCursor(cursor));
        } catch {
          // AI が自力で回復できる文面にする（詳しいエラー設計はセッション11 で扱います）
          return {
            isError: true,
            content: [
              {
                type: "text",
                text:
                  "cursor が不正です。cursor には前回のレスポンスの nextCursor をそのまま渡してください。" +
                  "先頭から取り直す場合は cursor を省略してください。",
              },
            ],
            // outputSchema を宣言しているツールでは、エラー時も構造化出力の形を崩さない
            structuredContent: { observations: [], returned: 0, hasMore: false },
          };
        }
      }

      const page = rows.slice(start, start + limit);
      const lastId = page.at(-1)?.id;
      const hasMore = start + page.length < rows.length;

      return {
        content: [
          {
            type: "text",
            text: `${page.length} 件を返しました（続き: ${hasMore ? "あり" : "なし"} / 該当 ${rows.length} 件）`,
          },
        ],
        structuredContent: {
          observations: page.map(toPublic),
          returned: page.length,
          // 最後のページでは nextCursor を付けない。これが「終わり」の合図になる
          ...(hasMore && lastId !== undefined ? { nextCursor: encodeCursor(lastId) } : {}),
          hasMore,
        },
      };
    },
  );

  // ---------------- 進捗通知とキャンセル ----------------
  server.registerTool(
    "aggregate_observations",
    {
      title: "観測データの集計",
      description:
        "全観測レコードを観測所ごとに集計します。処理に数秒かかるため、進捗通知を送り、" +
        "キャンセルにも対応します。件数が多い場合は stationId で絞り込むと速くなります。",
      inputSchema: {
        stationId: z
          .string()
          .optional()
          .describe("観測所 ID で絞り込みます（例: st-01）。省略すると全観測所を集計します"),
        chunkDelayMs: z
          .number()
          .int()
          .min(0)
          .max(1000)
          .default(120)
          .describe("1 チャンクあたりの疑似待ち時間（ミリ秒）。学習用の擬似負荷です"),
      },
      outputSchema: {
        totalObservations: z.number().int(),
        steps: z.number().int(),
        stations: z.array(
          z.object({
            stationId: z.string(),
            count: z.number().int(),
            avgTemperatureC: z.number(),
            maxTemperatureC: z.number(),
            totalPrecipitationMm: z.number(),
          }),
        ),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ stationId, chunkDelayMs }, extra) => {
      const all = getObservations();
      const rows = stationId === undefined ? all : all.filter((row) => row.stationId === stationId);
      const chunkSize = Math.ceil(rows.length / TOTAL_STEPS);
      // クライアントが進捗を要求したときだけ _meta.progressToken が入っている
      const progressToken = extra._meta?.progressToken;
      const acc = new Map<string, StationAccumulator>();
      let executedSteps = 0;

      lastRun = {
        tool: "aggregate_observations",
        totalSteps: TOTAL_STEPS,
        executedSteps: 0,
        finished: false,
        cancelled: false,
      };

      await sendLog(extra.sendNotification, "info", "集計を開始しました", {
        rows: rows.length,
        steps: TOTAL_STEPS,
      });

      try {
        for (let step = 0; step < TOTAL_STEPS; step++) {
          // ① ステップの入口でキャンセルを確認する
          extra.signal.throwIfAborted();
          // ② 重い I/O の代わりの疑似待ち。キャンセルされたら残り時間を待たない
          await sleepOrAbort(chunkDelayMs, extra.signal);

          accumulate(acc, rows.slice(step * chunkSize, (step + 1) * chunkSize));
          executedSteps = step + 1;

          await sendLog(
            extra.sendNotification,
            "debug",
            `チャンク ${executedSteps}/${TOTAL_STEPS} を集計しました`,
          );

          // ③ 進捗通知は「要求されたときだけ」送る
          if (progressToken !== undefined) {
            try {
              await extra.sendNotification({
                method: "notifications/progress",
                params: {
                  progressToken,
                  progress: executedSteps,
                  total: TOTAL_STEPS,
                  message: `${executedSteps}/${TOTAL_STEPS} チャンク完了`,
                },
              });
            } catch (error) {
              // 通知の失敗で集計を捨てない
              console.error("[progress] 通知の送信に失敗しました:", error);
            }
          }
        }
      } catch (error) {
        lastRun = {
          ...lastRun,
          executedSteps,
          finished: false,
          cancelled: extra.signal.aborted,
        };
        // 何ステップで止まったかは get_last_run_report から確認できるので、
        // stderr のログは実行ごとに変わらない文面にしておきます
        console.error(`[aggregate] 集計を中断しました（cancelled=${extra.signal.aborted}）`);
        throw error;
      }

      lastRun = {
        tool: "aggregate_observations",
        totalSteps: TOTAL_STEPS,
        executedSteps,
        finished: true,
        cancelled: false,
      };
      await sendLog(extra.sendNotification, "info", "集計が完了しました", { stations: acc.size });

      const stations = summarize(acc);
      return {
        content: [
          { type: "text", text: `${rows.length} 件を ${stations.length} 観測所に集計しました` },
        ],
        structuredContent: { totalObservations: rows.length, steps: executedSteps, stations },
      };
    },
  );

  // ---------------- キャンセルが効いたかを確認するためのツール ----------------
  server.registerTool(
    "get_last_run_report",
    {
      title: "直前の集計の実行記録",
      description:
        "直前に実行した aggregate_observations が何ステップ処理し、キャンセルされたかを返します。" +
        "キャンセル実装が本当に効いているかを確認するための検証用ツールです。",
      inputSchema: {},
      outputSchema: {
        tool: z.string(),
        totalSteps: z.number().int(),
        executedSteps: z.number().int(),
        finished: z.boolean(),
        cancelled: z.boolean(),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async () => ({
      content: [
        {
          type: "text",
          text: `${lastRun.executedSteps}/${lastRun.totalSteps} ステップ（finished=${lastRun.finished} / cancelled=${lastRun.cancelled}）`,
        },
      ],
      structuredContent: { ...lastRun },
    }),
  );

  // ---------------- list_changed ----------------
  const hourly = server.registerTool(
    "aggregate_observations_hourly",
    {
      title: "観測データの時間別集計（実験的）",
      description: "1 時間ごとのバケットで集計します。実験的機能のため、既定では無効です。",
      inputSchema: {},
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async () => ({
      content: [{ type: "text", text: "実験的機能です（本章では中身を実装しません）" }],
    }),
  );
  // 無効にすると tools/list に現れなくなる。AI に見せるツールを絞る手段でもある
  hourly.disable();

  server.registerTool(
    "enable_experimental_metrics",
    {
      title: "実験的な集計ツールを有効化する",
      description:
        "実験的な集計ツールを有効にします。有効化するとツール一覧が変わるため、" +
        "notifications/tools/list_changed が送られます。",
      inputSchema: {},
      annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      // enable() の時点で SDK が notifications/tools/list_changed を送ります
      hourly.enable();
      console.error("[tools] aggregate_observations_hourly を有効化しました");
      return {
        content: [{ type: "text", text: "aggregate_observations_hourly を有効化しました" }],
      };
    },
  );

  return server;
}
