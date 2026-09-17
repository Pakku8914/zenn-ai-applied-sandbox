/**
 * クライアント機能（sampling / roots / elicitation）の呼び出しラッパ
 *
 * 本章で SDK の「サーバー → クライアント」API を触るのはこのファイルだけです。
 * 3 つとも同じ形にそろえてあります。
 *   ① ケイパビリティを確認する（無いなら呼ばない）
 *   ② 呼ぶときは必ず timeout と signal を渡す
 *   ③ 失敗しても例外を投げず、判別可能な結果を返す（劣化の判断は呼び出し側）
 *
 * ここはサーバープロセス側のコードなので、ログは console.error（stderr）に出します。
 * stdout は JSON-RPC の通信路そのものなので console.log は使いません。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  type RequestId,
  type Root,
  RootsListChangedNotificationSchema,
} from "@modelcontextprotocol/sdk/types.js";

import {
  MAX_SUMMARY_TOKENS,
  MODEL_PREFERENCES,
  SUMMARY_SYSTEM_PROMPT,
  type SummaryMode,
} from "./domain/summary-prompt.js";

/** 待ち時間の上限。人間の操作を待つ elicitation だけ極端に長い */
export const ROOTS_TIMEOUT_MS = 5_000;
export const SAMPLING_TIMEOUT_MS = 30_000;
export const ELICITATION_TIMEOUT_MS = 120_000;

/**
 * 今処理しているツール呼び出しの文脈。
 * relatedRequestId を渡すと「どのリクエストに付随する依頼か」が伝わり、
 * Streamable HTTP では正しいストリームへ返ってきます（セッション7）。
 * signal を渡すと、ツールがキャンセルされたときに依頼も中断されます（セッション8）。
 */
export type CallContext = {
  readonly relatedRequestId: RequestId;
  readonly signal: AbortSignal;
};

export type FeatureSupport = {
  readonly sampling: boolean;
  readonly roots: boolean;
  readonly elicitation: boolean;
};

/** initialize で申告されたケイパビリティを読む。呼ぶ前に必ずここを通る */
export function detectSupport(server: McpServer): FeatureSupport {
  const capabilities = server.server.getClientCapabilities();
  return {
    sampling: capabilities?.sampling !== undefined,
    roots: capabilities?.roots !== undefined,
    elicitation: capabilities?.elicitation !== undefined,
  };
}

export type RootsCache = {
  read(): readonly Root[] | undefined;
  write(roots: readonly Root[]): void;
  invalidate(): void;
};

/**
 * roots をキャッシュし、notifications/roots/list_changed が来たら捨てる。
 *
 * キャッシュだけ実装して通知を無視すると、ユーザーが作業ディレクトリを変えたあとも
 * 古い境界で動き続けます。「境界のキャッシュ」は事故の温床なので、
 * 捨てる仕組みと必ずセットで書きます。
 */
export function installRootsCache(server: McpServer): RootsCache {
  let cached: readonly Root[] | undefined;
  server.server.setNotificationHandler(RootsListChangedNotificationSchema, () => {
    cached = undefined;
    console.error("[session09] roots が変更されたのでキャッシュを破棄しました");
  });
  return {
    read: () => cached,
    write: (roots) => {
      cached = roots;
    },
    invalidate: () => {
      cached = undefined;
    },
  };
}

export async function fetchRoots(
  server: McpServer,
  cache: RootsCache,
  context: CallContext,
): Promise<{ ok: true; roots: readonly Root[]; cached: boolean } | { ok: false }> {
  const hit = cache.read();
  if (hit !== undefined) {
    return { ok: true, roots: hit, cached: true };
  }
  try {
    const result = await server.server.listRoots(undefined, {
      relatedRequestId: context.relatedRequestId,
      signal: context.signal,
      timeout: ROOTS_TIMEOUT_MS,
    });
    cache.write(result.roots);
    return { ok: true, roots: result.roots, cached: false };
  } catch (error) {
    console.error("[session09] roots/list に失敗しました:", describeError(error));
    return { ok: false };
  }
}

export type SummaryOutcome =
  | { ok: true; text: string; model: string; stopReason: string | undefined }
  | { ok: false; reason: "call_failed" | "non_text_response" };

/** sampling でクライアントの LLM に要約を依頼する */
export async function requestSummary(
  server: McpServer,
  params: { promptText: string; mode: SummaryMode },
  context: CallContext,
): Promise<SummaryOutcome> {
  const preference = MODEL_PREFERENCES[params.mode];
  try {
    const result = await server.server.createMessage(
      {
        messages: [{ role: "user", content: { type: "text", text: params.promptText } }],
        systemPrompt: SUMMARY_SYSTEM_PROMPT,
        maxTokens: MAX_SUMMARY_TOKENS,
        // 他サーバーの会話文脈を混ぜない。既定で "none" にしておくのが安全側
        includeContext: "none",
        // 同じ入力なら同じ結果に近づける（サーバーの出力は下流のモデルの入力になる）
        temperature: 0,
        // モデルID は書かない。「どんなモデルが欲しいか」を数値で伝える
        modelPreferences: {
          costPriority: preference.costPriority,
          speedPriority: preference.speedPriority,
          intelligencePriority: preference.intelligencePriority,
        },
      },
      {
        relatedRequestId: context.relatedRequestId,
        signal: context.signal,
        timeout: SAMPLING_TIMEOUT_MS,
      },
    );
    // 画像や音声が返ってくることもある。text 以外は扱わないと決めておく
    if (result.content.type !== "text") {
      return { ok: false, reason: "non_text_response" };
    }
    return {
      ok: true,
      text: result.content.text.trim(),
      model: result.model,
      stopReason: result.stopReason,
    };
  } catch (error) {
    console.error("[session09] sampling/createMessage に失敗しました:", describeError(error));
    return { ok: false, reason: "call_failed" };
  }
}

export type NarrowOutcome =
  | { kind: "answered"; value: string }
  | { kind: "declined" }
  | { kind: "cancelled" }
  | { kind: "failed" }
  | { kind: "invalid" };

/** elicitation でユーザーに絞り込み先を尋ねる */
export async function askNarrowing(
  server: McpServer,
  params: { message: string; candidates: readonly string[]; allValue: string },
  context: CallContext,
): Promise<NarrowOutcome> {
  try {
    const result = await server.server.elicitInput(
      {
        message: params.message,
        // elicitation のスキーマはフラットなプリミティブだけ。オブジェクトの入れ子は使えない
        requestedSchema: {
          type: "object",
          properties: {
            directory: {
              type: "string",
              title: "検索対象のディレクトリ",
              description: "候補から 1 つ選んでください。絞り込まない場合は「すべて」を選びます。",
              enum: [...params.candidates, params.allValue],
              enumNames: [
                ...params.candidates.map((directory) => `${directory} のみを対象にする`),
                "すべて（絞り込まない）",
              ],
            },
          },
          required: ["directory"],
        },
      },
      {
        relatedRequestId: context.relatedRequestId,
        signal: context.signal,
        timeout: ELICITATION_TIMEOUT_MS,
      },
    );

    if (result.action === "decline") {
      return { kind: "declined" };
    }
    if (result.action === "cancel") {
      return { kind: "cancelled" };
    }
    // accept でも中身は検証する。スキーマを渡したこととクライアントが守ることは別問題
    const answer = result.content?.["directory"];
    if (typeof answer !== "string") {
      return { kind: "invalid" };
    }
    if (answer !== params.allValue && !params.candidates.includes(answer)) {
      return { kind: "invalid" };
    }
    return { kind: "answered", value: answer };
  } catch (error) {
    console.error("[session09] elicitation/create に失敗しました:", describeError(error));
    return { kind: "failed" };
  }
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
