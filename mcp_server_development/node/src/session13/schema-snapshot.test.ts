/**
 * スキーマの回帰テスト（2 段構え）
 *
 *   docker compose exec node npx vitest run src/session13/schema-snapshot.test.ts
 *
 *   ① 正規化ダイジェストを、テストに手で書いた期待値と比較する（意図の宣言）
 *   ② 生の tools/list をベースラインファイルと比較する（SDK 由来の変化まで検出）
 *
 * ② のベースラインは初回実行時に作られます。CI では SNAPSHOT_CI=1 を立て、
 *   「ベースラインが無いこと」自体を失敗にします（新規作成を黙って通さない）。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { createDocSearchServer } from "../mid01/create-server.js";
import { createFixtureServer } from "./fixture-server.js";
import { connectInMemory } from "./harness.js";
import { digestTools, outputRequiredOf, type ToolDigest } from "./schema-digest.js";

const DOCS_ROOT = path.resolve("src/mid01/docs");
const SNAPSHOT_DIR = path.resolve("src/session13/__snapshots__");

/**
 * ★ これが「守ると宣言した契約」です。
 *   引数名を 1 文字変えたらこの配列と食い違い、テストが赤くなります。
 *   Python 版のテストにも同じ期待値を書きます（2 言語で契約が一致していることの担保）。
 */
const SEARCH_TOOL_DIGEST: ToolDigest[] = [
  {
    name: "search_documents",
    title: "社内ドキュメントの全文検索",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    args: [
      { name: "directory", required: false, hasDescription: true },
      { name: "limit", required: false, hasDescription: true },
      { name: "query", required: true, hasDescription: true },
    ],
  },
];

async function listTools(server: ReturnType<typeof createFixtureServer>): Promise<unknown[]> {
  const client = await connectInMemory(server);
  const { tools } = await client.listTools();
  await client.close();
  return tools;
}

/**
 * ベースラインと比較する。
 * 文字列ではなく構造で比較するのが要点です（キーの並び順は取得経路で変わります）。
 */
function compareBaseline(name: string, actual: unknown): void {
  fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });
  const file = path.join(SNAPSHOT_DIR, `${name}.json`);
  const serialized = `${JSON.stringify(actual, null, 2)}\n`;

  if (!fs.existsSync(file)) {
    if (process.env["SNAPSHOT_CI"] === "1") {
      throw new Error(
        `ベースラインがありません: ${file}\n` +
          "CI では新規作成を許可しません。ローカルで作成し、内容を確認してコミットしてください。",
      );
    }
    fs.writeFileSync(file, serialized, "utf8");
    console.warn(`[snapshot] ベースラインを新規作成しました: ${file}（内容を確認してコミットしてください）`);
    return;
  }

  const baseline: unknown = JSON.parse(fs.readFileSync(file, "utf8"));
  expect(actual).toEqual(baseline);
}

describe("① 正規化ダイジェスト（期待値をテストに書く）", () => {
  it("search_documents の契約が宣言どおりである", async () => {
    const tools = await listTools(createDocSearchServer({ docsRoot: DOCS_ROOT }));

    expect(digestTools(tools)).toEqual(SEARCH_TOOL_DIGEST);
    // 出力スキーマの必須キーも契約の一部（省略可能な directory は含まれない）
    expect(outputRequiredOf(tools[0])).toEqual([
      "query",
      "results",
      "returned",
      "totalMatched",
      "truncated",
    ]);
  });
});

describe("② 生のスナップショット（SDK 由来の変化まで検出）", () => {
  it("mid01 の tools/list がベースラインと一致する", async () => {
    compareBaseline("mid01-tools-list", await listTools(createDocSearchServer({ docsRoot: DOCS_ROOT })));
  });

  it("fixture の tools/list がベースラインと一致する", async () => {
    compareBaseline("fixture-tools-list", await listTools(createFixtureServer()));
  });

  it("SDK が自動で足すフィールドが載っている（仕様改訂で変わりうる箇所）", async () => {
    const tools = await listTools(createFixtureServer());
    const first = tools[0] as Record<string, unknown>;
    const inputSchema = first["inputSchema"] as Record<string, unknown>;

    // 自分では書いていない 2 つ。増減したらプロトコル改訂の合図
    expect(inputSchema["$schema"]).toBe("http://json-schema.org/draft-07/schema#");
    expect(first["execution"]).toEqual({ taskSupport: "forbidden" });
  });
});
