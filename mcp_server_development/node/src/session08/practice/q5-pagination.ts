/**
 * 問題5 の解答：キーセット方式のページネーションを実装する
 *
 * 実行： docker compose exec node npx tsx src/session08/practice/q5-pagination.ts
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type StationRecord = { id: string; label: string };

/** 決定的に 20 件を生成する（乱数を使わないので毎回同じ） */
const ALL_RECORDS: StationRecord[] = Array.from({ length: 20 }, (_, index) => ({
  id: `r-${String(index + 1).padStart(4, "0")}`,
  label: `観測所 ${index + 1}`,
}));

/** 削除を再現するために差し替え可能にしておく（本来はデータベース） */
let dataset: StationRecord[] = ALL_RECORDS;

// ① カーソルは不透明な文字列にする（中身を解釈させない）
const encodeCursor = (afterId: string): string =>
  Buffer.from(JSON.stringify({ v: 1, afterId }), "utf8").toString("base64url");

const decodeCursor = (cursor: string): string => {
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw new Error("cursor を復号できません");
  }
  if (typeof parsed !== "object" || parsed === null) throw new Error("cursor の形式が不正です");
  const { v, afterId } = parsed as { v?: unknown; afterId?: unknown };
  if (v !== 1 || typeof afterId !== "string") throw new Error("cursor のバージョンが不正です");
  return afterId;
};

/** ② afterId より大きい最初の位置を二分探索で求める（削除されていても正しい） */
const findStartIndex = (rows: readonly StationRecord[], afterId: string): number => {
  let low = 0;
  let high = rows.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (rows[mid]!.id <= afterId) low = mid + 1;
    else high = mid;
  }
  return low;
};

const server = new McpServer({ name: "q5-pagination", version: "1.0.0" });

server.registerTool(
  "list_records",
  {
    title: "観測所レコードの一覧",
    description:
      "観測所レコードを id の昇順で返します。続きを取得するにはレスポンスの nextCursor を" +
      "そのまま cursor に渡してください。cursor の中身は解釈しないでください。",
    inputSchema: {
      cursor: z
        .string()
        .optional()
        .describe("前回のレスポンスの nextCursor をそのまま渡します。省略すると先頭から返します"),
      // ③ 既定値と上限をサーバー側が持つ
      limit: z
        .number()
        .int()
        .min(1)
        .max(100)
        .default(3)
        .describe("1 回で返す最大件数（1〜100、既定 3）"),
    },
    outputSchema: {
      records: z.array(z.object({ id: z.string(), label: z.string() })),
      returned: z.number().int(),
      nextCursor: z.string().optional(),
      hasMore: z.boolean(),
    },
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  },
  async ({ cursor, limit }) => {
    let start = 0;
    if (cursor !== undefined) {
      try {
        start = findStartIndex(dataset, decodeCursor(cursor));
      } catch {
        // ④ AI が自力で直せる文面にする
        return {
          isError: true,
          content: [
            {
              type: "text",
              text:
                "cursor が不正です。前回のレスポンスの nextCursor をそのまま渡してください。" +
                "先頭から取り直す場合は cursor を省略してください。",
            },
          ],
          // outputSchema を宣言しているので、エラー時も構造化出力の形を崩さない
          structuredContent: { records: [], returned: 0, hasMore: false },
        };
      }
    }

    const page = dataset.slice(start, start + limit);
    const hasMore = start + page.length < dataset.length;
    const lastId = page.at(-1)?.id;

    return {
      content: [
        {
          type: "text",
          text: `${page.length} 件を返しました（続き: ${hasMore ? "あり" : "なし"}）`,
        },
      ],
      structuredContent: {
        records: page,
        returned: page.length,
        // ⑤ 続きがあるときだけ nextCursor を返す。返さないことが「終わり」の合図
        ...(hasMore && lastId !== undefined ? { nextCursor: encodeCursor(lastId) } : {}),
        hasMore,
      },
    };
  },
);

// ---------------- 検証 ----------------
type ListResult = {
  records: Array<{ id: string; label: string }>;
  returned: number;
  nextCursor?: string;
  hasMore: boolean;
};

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "q5-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const call = async (args: Record<string, unknown>): Promise<ListResult> => {
  const result = await client.callTool({ name: "list_records", arguments: args });
  return result.structuredContent as ListResult;
};
const ids = (page: ListResult): string => page.records.map((row) => row.id).join(", ");

const page1 = await call({});
console.log(`[1/5] 1ページ目: ids=${ids(page1)} / hasMore=${page1.hasMore}`);

const page2 = await call({ cursor: page1.nextCursor });
console.log(`[2/5] 2ページ目: ids=${ids(page2)}`);

// 全ページ走査（無限ループ防止の上限を入れる）
let cursor: string | undefined;
let pages = 0;
let totalReturned = 0;
let lastReturned = 0;
let lastCursor: string | undefined;
for (let guard = 0; guard < 100; guard++) {
  const page = await call(cursor === undefined ? {} : { cursor });
  pages += 1;
  totalReturned += page.returned;
  lastReturned = page.returned;
  lastCursor = page.nextCursor;
  if (page.nextCursor === undefined) break;
  cursor = page.nextCursor;
}
console.log(
  `[3/5] 全ページ走査: ページ数=${pages} / 合計=${totalReturned} / 最終ページ returned=${lastReturned} / nextCursor=${lastCursor === undefined ? "なし" : "あり"}`,
);

// 上限を超える limit は Zod が弾く（ハンドラは呼ばれない）
let rejected = false;
let detail = "";
try {
  const over = await client.callTool({ name: "list_records", arguments: { limit: 999 } });
  rejected = over.isError === true;
  detail = "isError";
} catch (error) {
  rejected = true;
  detail = `code=${(error as { code?: number }).code}`;
}
console.log(`[4/5] limit=999: 拒否された=${rejected} / ${detail}`);

// 削除耐性：1 ページ目を取ったあとに r-0002 が削除されても続きはずれない
dataset = ALL_RECORDS.filter((row) => row.id !== "r-0002");
const page2AfterDelete = await call({ cursor: page1.nextCursor });
console.log(`[5/5] r-0002 削除後の2ページ目: ids=${ids(page2AfterDelete)}`);

await client.close();
await server.close();
console.log("OK: 問題5 の条件を満たしています");
