/**
 * 問題5 の解答 ―― 進捗通知とキャンセルに対応した走査ツール
 *
 * 登録する側（サーバー定義）と検証する側（クライアント）を分けています。
 * こうしておくと、問題7 で同じツールを HTTP で公開できます。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { DOCS } from "./docsearch-lite.js";

export type ScanReport = {
  totalSteps: number;
  executedSteps: number;
  finished: boolean;
  cancelled: boolean;
  /** 進捗通知を送ろうとした回数。要求されていないときに 0 であることを確認するために数える */
  progressAttempts: number;
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

export function registerScanTool(server: McpServer): void {
  let last: ScanReport = {
    totalSteps: DOCS.length,
    executedSteps: 0,
    finished: false,
    cancelled: false,
    progressAttempts: 0,
  };

  server.registerTool(
    "scan_documents",
    {
      title: "全文書の走査",
      description:
        "公開中の文書を 1 件ずつ走査して文字数を集計します。処理に時間がかかるため、" +
        "進捗通知を送り、キャンセルにも対応します。",
      inputSchema: {
        perDocDelayMs: z
          .number()
          .int()
          .min(0)
          .max(500)
          .default(60)
          .describe("1 文書あたりの疑似待ち時間（ミリ秒）。学習用の擬似負荷です"),
      },
      outputSchema: {
        scanned: z.number().int(),
        totalChars: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async ({ perDocDelayMs }, extra) => {
      // クライアントが進捗を要求したときだけ _meta.progressToken が入っている
      const progressToken = extra._meta?.progressToken;
      let executedSteps = 0;
      let totalChars = 0;
      let progressAttempts = 0;

      last = {
        totalSteps: DOCS.length,
        executedSteps: 0,
        finished: false,
        cancelled: false,
        progressAttempts: 0,
      };

      try {
        for (const doc of DOCS) {
          // ① 区切りでキャンセルを確認する
          extra.signal.throwIfAborted();
          // ② 疑似負荷。キャンセルされたら残り時間を待たない
          await sleepOrAbort(perDocDelayMs, extra.signal);

          totalChars += doc.title.length + doc.body.length;
          executedSteps += 1;

          // ③ 進捗通知は「要求されたときだけ」送る
          if (progressToken !== undefined) {
            progressAttempts += 1;
            try {
              await extra.sendNotification({
                method: "notifications/progress",
                params: {
                  progressToken,
                  progress: executedSteps,
                  total: DOCS.length,
                  message: `${executedSteps}/${DOCS.length} 件を走査しました`,
                },
              });
            } catch (error) {
              // 通知の失敗で走査を捨てない（通知は応答が返らない片道の仕組み）
              console.error("[scan] 進捗通知の送信に失敗しました:", error);
            }
          }
        }
      } catch (error) {
        last = {
          totalSteps: DOCS.length,
          executedSteps,
          finished: false,
          cancelled: extra.signal.aborted,
          progressAttempts,
        };
        // 何件で止まったかは get_last_scan_report で読めるので、
        // stderr のログは実行ごとに変わらない文面にしておく
        console.error(`[scan] 走査を中断しました（cancelled=${extra.signal.aborted}）`);
        throw error;
      }

      last = {
        totalSteps: DOCS.length,
        executedSteps,
        finished: true,
        cancelled: false,
        progressAttempts,
      };
      return {
        content: [
          {
            type: "text" as const,
            text: `${executedSteps} 件を走査しました（合計 ${totalChars} 文字）`,
          },
        ],
        structuredContent: { scanned: executedSteps, totalChars },
      };
    },
  );

  server.registerTool(
    "get_last_scan_report",
    {
      title: "直前の走査の実行記録",
      description:
        "直前に実行した scan_documents が何件処理し、キャンセルされたかを返します。" +
        "キャンセル実装が本当に効いているかを確認するための検証用ツールです。",
      inputSchema: {},
      outputSchema: {
        totalSteps: z.number().int(),
        executedSteps: z.number().int(),
        finished: z.boolean(),
        cancelled: z.boolean(),
        progressAttempts: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async () => ({
      content: [
        {
          type: "text" as const,
          text: `${last.executedSteps}/${last.totalSteps} 件（finished=${last.finished} / cancelled=${last.cancelled}）`,
        },
      ],
      structuredContent: { ...last },
    }),
  );
}
