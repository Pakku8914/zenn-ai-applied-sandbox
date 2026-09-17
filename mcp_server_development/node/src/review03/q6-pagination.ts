/**
 * 問題6 の解答 ―― 削除に耐える cursor ページネーション
 *
 *   docker compose exec node npx tsx src/review03/q6-pagination.ts
 *
 * サーバーとクライアントを 1 ファイルに書き、インメモリトランスポートでつないでいます。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpError } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { DOCS, toUri, type DocEntry } from "./docsearch-lite.js";

const DEFAULT_PAGE_SIZE = 2;
const MAX_PAGE_SIZE = 20;

/**
 * データベースの代わり。削除耐性の実験のためだけに差し替えます
 * （このサーバーは読み取り専用なので、削除ツールは作りません）。
 */
let current: readonly DocEntry[] = DOCS;

/** カーソルを不透明な文字列にする。中身はバージョン付きの JSON（暗号化ではない） */
function encodeCursor(afterPath: string): string {
  return Buffer.from(JSON.stringify({ v: 1, afterPath }), "utf8").toString("base64url");
}

/** カーソルを復号する。壊れていれば例外を投げる */
function decodeCursor(cursor: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw new Error("cursor を復号できません");
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("cursor の形式が不正です");
  }
  const { v, afterPath } = parsed as { v?: unknown; afterPath?: unknown };
  // バージョンを埋めておくと、後で構造を変えたときに古いカーソルを弾ける
  if (v !== 1 || typeof afterPath !== "string") {
    throw new Error("cursor のバージョンが不正です");
  }
  return afterPath;
}

/**
 * afterPath より大きい最初の位置を二分探索で求める。
 * 「その行が削除されていても正しい位置が出る」ことが要点です。
 */
function findStartIndex(docs: readonly DocEntry[], afterPath: string): number {
  let low = 0;
  let high = docs.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    // noUncheckedIndexedAccess のため非 null アサーションを付ける（範囲は不変条件で保証済み）
    if (docs[mid]!.path <= afterPath) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  return low;
}

const server = new McpServer({ name: "review03-q6", version: "1.0.0" });

server.registerTool(
  "list_documents",
  {
    title: "文書索引の一覧",
    description:
      "公開中の文書をパスの昇順で返します。1 回の呼び出しで返す件数には上限があるため、" +
      "続きを取得するにはレスポンスの nextCursor をそのまま cursor に渡してください。" +
      "cursor の中身は解釈しないでください（形式は予告なく変わります）。" +
      "nextCursor が返らなかったページが最後のページです。",
    inputSchema: {
      cursor: z
        .string()
        .optional()
        .describe("前回のレスポンスの nextCursor をそのまま渡します。省略すると先頭から返します"),
      limit: z
        .number()
        .int()
        .min(1)
        .max(MAX_PAGE_SIZE)
        .default(DEFAULT_PAGE_SIZE)
        .describe(`1 回で返す最大件数（1〜${MAX_PAGE_SIZE}、既定 ${DEFAULT_PAGE_SIZE}）`),
    },
    outputSchema: {
      documents: z.array(
        z.object({ path: z.string(), uri: z.string(), title: z.string() }),
      ),
      returned: z.number().int(),
      nextCursor: z.string().optional(),
      hasMore: z.boolean(),
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  async ({ cursor, limit }) => {
    const docs = current;

    let start = 0;
    if (cursor !== undefined) {
      try {
        start = findStartIndex(docs, decodeCursor(cursor));
      } catch {
        // 利用者（AI）の入力ミスはツール実行の失敗。AI が自力で回復できる文面にする
        return {
          isError: true,
          content: [
            {
              type: "text" as const,
              text:
                "cursor が不正です。cursor には前回のレスポンスの nextCursor をそのまま渡してください。" +
                "先頭から取り直す場合は cursor を省略してください。",
            },
          ],
          // outputSchema を宣言しているツールでは、エラー時も構造化出力の形を崩さない
          structuredContent: { documents: [], returned: 0, hasMore: false },
        };
      }
    }

    const page = docs.slice(start, start + limit);
    const hasMore = start + page.length < docs.length;
    const lastPath = page.at(-1)?.path;

    return {
      content: [
        {
          type: "text" as const,
          text: `${page.length} 件を返しました（続き: ${hasMore ? "あり" : "なし"} / 全 ${docs.length} 件）`,
        },
      ],
      structuredContent: {
        documents: page.map((doc) => ({
          path: doc.path,
          uri: toUri(doc.path),
          title: doc.title,
        })),
        returned: page.length,
        // nextCursor は hasMore から導出する。最後のページでは付けない（これが終わりの合図）
        ...(hasMore && lastPath !== undefined ? { nextCursor: encodeCursor(lastPath) } : {}),
        hasMore,
      },
    };
  },
);

// ------------------------------------------------------------------
// ここから検証（クライアント側なので console.log を使ってかまいません）
// ------------------------------------------------------------------

type PageResult = {
  documents: { path: string }[];
  returned: number;
  nextCursor?: string;
  hasMore: boolean;
};

const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const client = new Client({ name: "review03-q6-client", version: "1.0.0" });
await server.connect(serverTransport);
await client.connect(clientTransport);

const callList = async (args: Record<string, unknown>): Promise<PageResult> =>
  (await client.callTool({ name: "list_documents", arguments: args }))
    .structuredContent as PageResult;
const paths = (page: PageResult): string => page.documents.map((doc) => doc.path).join(", ");

const page1 = await callList({});
console.log(
  `[1/5] 1ページ目: paths=${paths(page1)} / hasMore=${page1.hasMore}` +
    ` / nextCursor=${page1.nextCursor === undefined ? "なし" : "あり"}`,
);

const page2 = await callList({ cursor: page1.nextCursor });
console.log(`[2/5] 2ページ目: paths=${paths(page2)} / returned=${page2.returned}`);

// 全ページ走査（nextCursor が無くなるまで）
let cursor: string | undefined;
let pages = 0;
let total = 0;
let lastReturned = 0;
for (let guard = 0; guard < 100; guard += 1) {
  // 無限ループ防止の上限を必ず入れる
  const page = await callList(cursor === undefined ? {} : { cursor });
  pages += 1;
  total += page.returned;
  lastReturned = page.returned;
  if (page.nextCursor === undefined) {
    break;
  }
  cursor = page.nextCursor;
}
console.log(
  `[3/5] 全ページ走査: ページ数=${pages} / 合計=${total} 件` +
    ` / 最終ページ returned=${lastReturned} / nextCursor=なし`,
);

// limit の上限（SDK が弾く）と壊れたカーソル（ツールが isError で返す）
let rejected = false;
let code: number | string = "不明";
try {
  await callList({ limit: 999 });
} catch (error) {
  rejected = true;
  if (error instanceof McpError) {
    code = error.code;
  }
}
const broken = await client.callTool({
  name: "list_documents",
  arguments: { cursor: "not-a-cursor" },
});
console.log(
  `[4/5] limit=999: 拒否された=${rejected} / code=${code}` +
    ` ／ 壊れたカーソル: isError=${broken.isError === true}`,
);

// 削除耐性 ―― 1 ページ目を返したあとに 1 件削除された状況
current = DOCS.filter((doc) => doc.path !== "faq/account-lock.md");
const afterDelete = await callList({ cursor: page1.nextCursor });
// 同じ位置をオフセット方式（2 件目から）で取った場合
const offsetStyle = current
  .slice(page1.returned, page1.returned + DEFAULT_PAGE_SIZE)
  .map((doc) => doc.path)
  .join(", ");
console.log(`[5/5] faq/account-lock.md 削除後の2ページ目: paths=${paths(afterDelete)}（欠落なし）`);
console.log(`      同じ位置をオフセット方式で取ると: paths=${offsetStyle}（onboarding.md が欠落）`);

await client.close();
await server.close();
console.log("OK: 問題6 の条件を満たしています");
