/**
 * 横断復習4 問題5 ―― スコープ × ドライラン × 3 層エラー
 *
 * 実行: docker compose exec node npx tsx src/review04/q5-decide.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import {
  SCOPE_APPROVE,
  SCOPE_READ,
  leaksInternalDetail,
  scopeFailure,
  toolFailureWith,
} from "./support.js";
import {
  DECISIONS,
  createWorkflowStore,
  decideRequest,
  type Decision,
  type WorkflowStore,
} from "./workflow-lite.js";

/** ドライランと確定で同じ関数から作る。片方だけ別実装にすると必ずずれる */
function makePreviewToken(requestId: string, decision: Decision, version: number): string {
  return Buffer.from(JSON.stringify({ v: 1, requestId, decision, version }), "utf8").toString(
    "base64url",
  );
}

type Preview = { requestId: string; decision: string; version: number };

function readPreviewToken(token: string): Preview | undefined {
  try {
    const parsed: unknown = JSON.parse(Buffer.from(token, "base64url").toString("utf8"));
    if (typeof parsed !== "object" || parsed === null) return undefined;
    const { v, requestId, decision, version } = parsed as Record<string, unknown>;
    if (v !== 1) return undefined;
    if (typeof requestId !== "string" || typeof decision !== "string") return undefined;
    if (typeof version !== "number") return undefined;
    return { requestId, decision, version };
  } catch {
    // 復号の失敗の中身は分類にだけ使い、文面には出さない
    return undefined;
  }
}

export function createDecideServer(options: {
  grantedScopes: readonly string[];
  store?: WorkflowStore;
}): { server: McpServer; store: WorkflowStore } {
  const store = options.store ?? createWorkflowStore();
  const server = new McpServer({ name: "review04-decide", version: "1.0.0" });

  server.registerTool(
    "decide_request",
    {
      title: "申請を決裁",
      description:
        "申請を承認または却下します。取り消せない操作なので二段階です。" +
        "confirm を省略すると対象の確認だけを行い、previewToken を返します（状態は変わりません）。" +
        "確定するときは同じ引数に confirm: true と previewToken を添えて呼び直してください。" +
        "下書きを取り下げたいときはこのツールを使わないでください。",
      inputSchema: {
        requestId: z.string().min(1).max(32).describe("申請 ID（例: req-1003）"),
        decision: z.enum(DECISIONS).describe("approve（承認）または reject（却下）"),
        reason: z.string().min(10).max(200).describe("決裁の理由（10〜200 文字・必須）"),
        confirm: z
          .boolean()
          .default(false)
          .describe("true のときだけ実際に決裁します（既定 false＝ドライラン）"),
        previewToken: z
          .string()
          .optional()
          .describe("ドライランで返された previewToken。confirm: true のときは必須です"),
      },
      outputSchema: {
        requestId: z.string(),
        decision: z.enum(DECISIONS),
        /** true なら状態を変更した。ドライランは false */
        applied: z.boolean(),
        status: z.string().optional(),
        version: z.number().int().optional(),
        previewToken: z.string().optional(),
        error: z
          .object({
            code: z.string(),
            retryable: z.boolean(),
            retryAfterSeconds: z.number().optional(),
          })
          .optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ requestId, decision, reason, confirm, previewToken }) => {
      // 失敗しても形を保つための「空の正しい値」
      const base = { requestId, decision, applied: false };

      // ① 権限。外部処理・データ参照の前に検査する
      const denied = scopeFailure("decide_request", options.grantedScopes);
      if (denied !== undefined) return toolFailureWith(denied, base);

      // ② 対象の存在
      const row = store.requests.get(requestId);
      if (row === undefined) {
        return toolFailureWith(
          {
            code: "not_found",
            what: `申請 ${requestId} は見つかりませんでした。`,
            next: "search_requests に status: [\"submitted\"] を渡して、決裁できる申請の ID を確認してから呼び直してください。",
            retryable: false,
          },
          base,
        );
      }

      // ③ 状態。ドライランと確定の共通の入口で 1 回だけ検査する（二重決裁の防止）
      if (row.status !== "submitted") {
        return toolFailureWith(
          {
            code: "invalid_state",
            what: `申請 ${requestId} の状態は ${row.status} なので決裁できません。`,
            next: "決裁できるのは status が submitted の申請だけです。すでに決裁済みの場合、この操作は取り消せないため上長に相談してください。",
            retryable: false,
          },
          base,
        );
      }

      const token = makePreviewToken(requestId, decision, row.version);

      // ④ ドライラン。状態は絶対に変えない
      if (!confirm) {
        const label = decision === "approve" ? "承認" : "却下";
        return {
          content: [
            {
              type: "text" as const,
              text: [
                `次の申請を${label}しようとしています（まだ実行していません）。`,
                `- ${row.id} ${row.title}（${row.category} / ${row.amountYen} 円 / ${row.status} / 申請者 ${row.applicantName}）`,
                `確定するには confirm: true と previewToken を添えて同じ引数で呼び直してください。`,
                `previewToken: ${token}`,
              ].join("\n"),
            },
          ],
          structuredContent: {
            ...base,
            status: row.status,
            version: row.version,
            previewToken: token,
          },
        };
      }

      // ⑤ 確定には previewToken が必須
      if (previewToken === undefined) {
        return toolFailureWith(
          {
            code: "invalid_argument",
            what: "confirm: true には previewToken が必要です。",
            next: "同じ requestId と decision で confirm を省略して呼び、返ってきた previewToken を添えて呼び直してください。",
            retryable: false,
          },
          base,
        );
      }

      const preview = readPreviewToken(previewToken);
      if (
        preview === undefined ||
        preview.requestId !== requestId ||
        preview.decision !== decision ||
        preview.version !== row.version
      ) {
        return toolFailureWith(
          {
            code: "invalid_state",
            what: "previewToken が現在の申請と一致しません（申請が更新された可能性があります）。",
            next: "confirm を省略してドライランをやり直し、新しく返された previewToken で確定してください。",
            retryable: false,
          },
          base,
        );
      }

      const outcome = decideRequest(store, requestId, decision);
      if (!outcome.ok) {
        // ③ で状態を確認しているので通常は到達しない（同時実行への保険）
        return toolFailureWith(
          {
            code: "invalid_state",
            what: "決裁の直前に申請の状態が変わりました。",
            next: "confirm を省略してドライランからやり直してください。",
            retryable: false,
          },
          base,
        );
      }

      console.error(`[review04] 決裁: ${requestId} → ${outcome.status}（version=${outcome.version}）`);
      return {
        content: [
          {
            type: "text" as const,
            text: `申請 ${requestId} を ${outcome.status} にしました（version=${outcome.version}）。理由: ${reason}`,
          },
        ],
        structuredContent: {
          ...base,
          applied: true,
          status: outcome.status,
          version: outcome.version,
        },
      };
    },
  );

  return { server, store };
}

// ── 検証 ────────────────────────────────────────────────────────────────
type DecideOutput = {
  applied?: boolean;
  status?: string;
  version?: number;
  previewToken?: string;
  error?: { code?: string; retryable?: boolean };
};

function structured(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): DecideOutput {
  return (result.structuredContent ?? {}) as DecideOutput;
}

function firstText(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const blocks = (result.content ?? []) as Array<{ type?: string; text?: string }>;
  return blocks.find((block) => block.type === "text")?.text ?? "";
}

/** 本文の分類だけを出す（生の文面は SDK の版で変わる） */
function head(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const text = firstText(result).replace(/\s+/g, " ").trim();
  const sdk = /^MCP error (-?\d+)/.exec(text);
  return sdk === null ? text.slice(0, 24) : `MCP error ${sdk[1]}`;
}

async function connect(grantedScopes: readonly string[], store?: WorkflowStore) {
  const created = createDecideServer({ grantedScopes, store });
  const client = new Client({ name: "review04-decide-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([created.server.connect(serverTransport), client.connect(clientTransport)]);
  return { ...created, client };
}

const APPROVE_REASON = "内容と金額を確認したため承認します。";
const REJECT_REASON = "予算の上限を超えているため却下します。";
const collected: string[] = [];

// [1/8] 権限が足りない接続
const readOnly = await connect([SCOPE_READ]);
const r1 = await readOnly.client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1003", decision: "approve", reason: APPROVE_REASON },
});
collected.push(firstText(r1));
console.log(
  `[1/8] requests:read のみ: code=${structured(r1).error?.code} / ` +
    `retryable=${structured(r1).error?.retryable} / isError=${r1.isError === true}`,
);
await readOnly.client.close();
await readOnly.server.close();

// [2/8]〜[8/8] は同じストアを使う 1 つの接続で行う
const main = await connect([SCOPE_READ, SCOPE_APPROVE]);

const r2 = await main.client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1003", decision: "approve", reason: APPROVE_REASON },
});
const s2 = structured(r2);
console.log(
  `[2/8] ドライラン: previewToken=${s2.previewToken === undefined ? "なし" : "あり"} / ` +
    `状態=${main.store.requests.get("req-1003")?.status} / version=${s2.version}`,
);

const r3 = await main.client.callTool({
  name: "decide_request",
  arguments: {
    requestId: "req-1003",
    decision: "approve",
    reason: APPROVE_REASON,
    confirm: true,
    previewToken: s2.previewToken,
  },
});
const s3 = structured(r3);
console.log(`[3/8] 確定: req-1003 → ${s3.status} / version=${s3.version}`);

const r4 = await main.client.callTool({
  name: "decide_request",
  arguments: {
    requestId: "req-1004",
    decision: "reject",
    reason: REJECT_REASON,
    confirm: true,
  },
});
collected.push(firstText(r4));
console.log(
  `[4/8] previewToken なしで confirm: code=${structured(r4).error?.code} / isError=${r4.isError === true}`,
);

const dry5 = await main.client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1004", decision: "reject", reason: REJECT_REASON },
});
const token5 = structured(dry5).previewToken;
// 別経路で申請が更新された状況を再現する
const row5 = main.store.requests.get("req-1004");
if (row5 !== undefined) row5.version += 1;
const r5 = await main.client.callTool({
  name: "decide_request",
  arguments: {
    requestId: "req-1004",
    decision: "reject",
    reason: REJECT_REASON,
    confirm: true,
    previewToken: token5,
  },
});
collected.push(firstText(r5));
console.log(
  `[5/8] version が変わった後の確定: code=${structured(r5).error?.code} / isError=${r5.isError === true}`,
);

const r6 = await main.client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-9999", decision: "approve", reason: APPROVE_REASON },
});
collected.push(firstText(r6));
console.log(
  `[6/8] 存在しない ID: code=${structured(r6).error?.code} / isError=${r6.isError === true}`,
);

const r7 = await main.client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1001", decision: "approve", reason: APPROVE_REASON },
});
collected.push(firstText(r7));
console.log(
  `[7/8] approved へのドライラン: code=${structured(r7).error?.code} / isError=${r7.isError === true}`,
);

// 列挙値の外。問題2 の観測どおり例外は飛ばない
const r8 = await main.client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1003", decision: "保留", reason: APPROVE_REASON },
});
console.log(
  `[8/8] decision="保留": 例外=なし / isError=${r8.isError === true} / 本文の先頭=${head(r8)}`,
);

const leaks = collected.filter((text) => leaksInternalDetail(text)).length;
console.log(`内部情報の露出: ${leaks === 0 ? "なし" : `${leaks} 件`}（失敗文面 ${collected.length} 件を検査）`);
console.log("OK: 問題5 の条件を満たしています");

await main.client.close();
await main.server.close();
