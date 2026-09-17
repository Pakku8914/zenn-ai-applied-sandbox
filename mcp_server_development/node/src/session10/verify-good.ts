/**
 * Good 実装の動作確認
 *
 * 実行： docker compose exec node npx tsx src/session10/verify-good.ts
 *
 * クライアント側のスクリプトなので console.log を使ってかまいません
 * （禁止されているのは「サーバープロセスの stdout」だけです）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { createWorkflowServer } from "./good-create-server.js";

/** ツール結果の 1 つめのテキストを取り出す */
function text(result: { content?: unknown; structuredContent?: unknown; isError?: boolean; [key: string]: unknown }): string {
  const first = (result.content as Array<{ type: string; text?: string }> | undefined)?.[0];
  return first?.text ?? "";
}

/** ドライランの出力から previewToken を拾う */
function pickToken(message: string): string {
  return /previewToken: (\S+)/.exec(message)?.[1] ?? "";
}

const { server } = createWorkflowServer();
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "session10-verify", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const names = (await client.listTools()).tools.map((tool) => tool.name).sort();
console.log(`[1/9] tools/list: ${names.length} 本 = ${names.join(", ")}`);

const searched = await client.callTool({
  name: "search_requests",
  arguments: { status: ["in_review"] },
});
const structured = searched.structuredContent as {
  total: number;
  items: Array<{ id: string }>;
};
console.log(
  `[2/9] search_requests(status=["in_review"]): total=${structured.total} ids=${structured.items
    .map((item) => item.id)
    .join(", ")}`,
);

const detail = text(
  await client.callTool({
    name: "get_request",
    arguments: { requestId: "req-1003", include: ["comments"] },
  }),
);
console.log(
  `[3/9] get_request(req-1003, include=["comments"]): ` +
    `コメント=${/コメント（(\d+) 件）/.exec(detail)?.[1] ?? "0"} 件 / ` +
    `添付=${detail.includes("添付（") ? "含まれる" : "含まれない"} / ` +
    `履歴=${detail.includes("履歴（") ? "含まれる" : "含まれない"}`,
);

const created = text(
  await client.callTool({
    name: "save_request",
    arguments: {
      title: "書籍購入（技術書 3 冊）",
      category: "purchase",
      amountYen: 12_000,
      body: "チームの技術書を 3 冊購入します。",
    },
  }),
);
const newId = /^(req-\d{4})/.exec(created)?.[1] ?? "";
console.log(`[4/9] save_request(新規): ${created.split("\n")[0]}`);

const updated = text(
  await client.callTool({
    name: "save_request",
    arguments: { requestId: newId, amountYen: 24_000 },
  }),
);
console.log(`[5/9] save_request(更新): ${updated.split("\n")[0]}`);

const submitDry = text(
  await client.callTool({ name: "submit_request", arguments: { requestId: newId } }),
);
console.log(
  `[6/9] submit_request(ドライラン): ${submitDry.split("\n")[1]} / previewToken=${
    pickToken(submitDry) === "" ? "なし" : "あり"
  }`,
);

const submitted = text(
  await client.callTool({
    name: "submit_request",
    arguments: { requestId: newId, confirm: true, previewToken: pickToken(submitDry) },
  }),
);
console.log(`[7/9] submit_request(確定): ${submitted}`);

const decideDry = await client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1003", decision: "approve" },
});
const dryStructured = decideDry.structuredContent as {
  applied: boolean;
  stepLabel: string;
  nextStatus: string;
  finalizes: boolean;
  previewToken?: string;
};
console.log(
  `[8/9] decide_request(ドライラン): applied=${dryStructured.applied} ` +
    `${dryStructured.stepLabel} 確定後=${dryStructured.nextStatus} ` +
    `審査終了=${dryStructured.finalizes ? "はい" : "いいえ"}`,
);

const decided = await client.callTool({
  name: "decide_request",
  arguments: {
    requestId: "req-1003",
    decision: "approve",
    confirm: true,
    previewToken: dryStructured.previewToken,
  },
});
console.log(`[9/9] decide_request(確定): ${text(decided).split("\n")[0]}`);

// ── 異常系（二段階が本当に効いているかの確認） ──
const noToken = await client.callTool({
  name: "decide_request",
  arguments: { requestId: "req-1002", decision: "approve", confirm: true },
});
console.log(`[異常系1] previewToken なしで confirm: isError=${noToken.isError === true}`);

const staleDry = text(
  await client.callTool({
    name: "decide_request",
    arguments: { requestId: "req-1002", decision: "approve" },
  }),
);
// プレビュー後に申請が変わったことを再現する（コメントを 1 件付ける）
await client.callTool({
  name: "comment_on_request",
  arguments: { requestId: "req-1002", body: "追加の見積を確認しました。" },
});
const stale = await client.callTool({
  name: "decide_request",
  arguments: {
    requestId: "req-1002",
    decision: "approve",
    confirm: true,
    previewToken: pickToken(staleDry),
  },
});
console.log(`[異常系2] 申請が変わった後の previewToken: isError=${stale.isError === true}`);

await client.close();
await server.close();
console.log("OK: セッション10 の Good 実装は仕様どおりに動作しています");
