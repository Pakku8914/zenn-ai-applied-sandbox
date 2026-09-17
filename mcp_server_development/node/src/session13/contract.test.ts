/**
 * 中間プロジェクト1 の契約テスト（問題2・問題3 の解答）
 *
 *   docker compose exec node npx vitest run src/session13/contract.test.ts
 *
 * 中間プロジェクト1 の mid01.test.ts の「続き」として、そこでは固定していなかった
 * 約束を足します。
 *   ① 正常系（注釈・content と structuredContent の整合・0 件）
 *   ② 異常系（スキーマ層で落ちるもの／ドメイン層で落ちるもの／未知のツール）
 *   ③ 層の違い（同じ入力でも tools/call と prompts/get で返るものが違う）
 *   ④ 決定性（同じ入力なら同じ出力）
 *
 * mid01 のファイルは読み取り専用で import します（1 文字も書き換えません）。
 */
import path from "node:path";

import { describe, expect, it } from "vitest";

import { createDocSearchServer } from "../mid01/create-server.js";
import { callTool, connectInMemory, expectToolFailure, toolText } from "./harness.js";

const DOCS_ROOT = path.resolve("src/mid01/docs");

/** テストごとに新しいサーバー定義を作る（テスト間で状態を共有しない） */
function docSearchServer() {
  return createDocSearchServer({ docsRoot: DOCS_ROOT });
}

type SearchStructured = {
  readonly totalMatched: number;
  readonly returned: number;
  readonly results: readonly { readonly path: string; readonly uri: string }[];
};

function structuredOf(result: { readonly structuredContent?: Record<string, unknown> }): SearchStructured {
  if (result.structuredContent === undefined) {
    throw new Error("structuredContent が返っていません（outputSchema を宣言したツールでは必須）");
  }
  return result.structuredContent as unknown as SearchStructured;
}

describe("① 正常系の契約", () => {
  it("tools/list がツール 1 本・注釈 4 つ・outputSchema を返す", async () => {
    const client = await connectInMemory(docSearchServer());
    const { tools } = await client.listTools();

    expect(tools).toHaveLength(1);
    expect(tools[0]?.name).toBe("search_documents");
    expect(tools[0]?.title).toBe("社内ドキュメントの全文検索");
    // 4 つすべて明示されていること（省略すると「不明」扱いになり、ホストが確認を求める）
    expect(tools[0]?.annotations).toMatchObject({
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    });
    expect(tools[0]?.outputSchema).toBeDefined();
    await client.close();
  });

  it("resource_link の件数と structuredContent.results の件数が一致する", async () => {
    const client = await connectInMemory(docSearchServer());
    // 先に listTools を呼ぶと、クライアント側の outputSchema 検証も一緒に働く
    await client.listTools();
    const result = await callTool(client, "search_documents", { query: "VPN" });
    const structured = structuredOf(result);

    const links = result.content.filter((block) => block.type === "resource_link");
    expect(structured.totalMatched).toBe(4);
    expect(links).toHaveLength(structured.results.length);
    // 並び順まで一致していること（片方だけ並べ替える回帰を防ぐ）
    expect(links.map((block) => block.uri)).toEqual(structured.results.map((hit) => hit.uri));
    // 先頭は要約の text。本文は載せない設計を固定する
    expect(result.content[0]?.type).toBe("text");
    expect(toolText(result)).not.toContain("VPN クライアントの導入");
    await client.close();
  });

  it("0 件でも isError にならず、results は空配列で返る", async () => {
    const client = await connectInMemory(docSearchServer());
    const result = await callTool(client, "search_documents", { query: "ゼロトラスト" });

    // 「探したが無かった」は正常な検索結果。isError にするとホストが赤いエラーを出す
    expect(result.isError ?? false).toBe(false);
    const structured = structuredOf(result);
    expect(structured.totalMatched).toBe(0);
    expect(structured.results).toEqual([]);
    expect(toolText(result)).toContain("に一致する文書はありませんでした");
    await client.close();
  });
});

describe("② 異常系はすべて isError で届く", () => {
  // スキーマ層（SDK が検証する）で落ちるもの
  const schemaViolations: [string, Record<string, unknown>][] = [
    ["limit が下限を下回る", { query: "VPN", limit: 0 }],
    ["limit が上限を超える", { query: "VPN", limit: 100 }],
    ["query が無い", {}],
    ["query の型が違う", { query: 42 }],
  ];

  it.each(schemaViolations)("%s → スキーマ層の失敗", async (_label, args) => {
    const client = await connectInMemory(docSearchServer());
    const message = expectToolFailure(await callTool(client, "search_documents", args));

    expect(message).toContain("-32602");
    expect(message).toContain("Invalid arguments for tool search_documents");
    await client.close();
  });

  // ドメイン層（自分のコードが検証する）で落ちるもの
  const domainFailures: [string, Record<string, unknown>, string][] = [
    ["空白だけの検索語", { query: "   " }, "検索語を 1 文字以上で指定してください。"],
    ["存在しないディレクトリ", { query: "VPN", directory: "secret" }, "directory に指定できるのは"],
  ];

  it.each(domainFailures)("%s → ドメイン層の失敗", async (_label, args, expected) => {
    const client = await connectInMemory(docSearchServer());
    const message = expectToolFailure(await callTool(client, "search_documents", args));

    expect(message).toContain(expected);
    // スキーマ層の失敗と混同しないように、こちらには -32602 が入らないことも固定する
    expect(message).not.toContain("-32602");
    await client.close();
  });

  it("存在しないツール名も isError で返る", async () => {
    const client = await connectInMemory(docSearchServer());
    const message = expectToolFailure(await callTool(client, "delete_everything", {}));

    expect(message).toContain("Tool delete_everything not found");
    await client.close();
  });
});

describe("③ 同じ入力でも、層が違えばエラーの形が違う", () => {
  it("空白だけの検索語は、tools/call では isError・prompts/get では JSON-RPC エラー", async () => {
    const client = await connectInMemory(docSearchServer());

    // ツール実行層：モデルに理由を届けたいので isError
    const toolResult = await callTool(client, "search_documents", { query: "   " });
    expect(toolResult.isError).toBe(true);
    expect(toolText(toolResult)).toContain("検索語を 1 文字以上で指定してください。");

    // プロンプト：isError はツール専用の仕組みなので JSON-RPC エラーになる
    await expect(
      client.getPrompt({ name: "summarize_search", arguments: { query: "   " } }),
    ).rejects.toMatchObject({ code: -32602 });

    await client.close();
  });

  it("resources/read のパストラバーサルは JSON-RPC エラー", async () => {
    const client = await connectInMemory(docSearchServer());

    await expect(client.readResource({ uri: "docs://../../etc/passwd" })).rejects.toMatchObject({
      code: -32602,
    });

    await client.close();
  });
});

describe("④ 決定性", () => {
  it("同じ入力なら、キーの並びまで同じ structuredContent が返る", async () => {
    const client = await connectInMemory(docSearchServer());
    const first = await callTool(client, "search_documents", { query: "VPN" });
    const second = await callTool(client, "search_documents", { query: "VPN" });

    // 構造ではなく文字列で比較する（「同じ入力なら同じバイト列」を固定したいので）
    expect(JSON.stringify(second.structuredContent)).toBe(JSON.stringify(first.structuredContent));
    await client.close();
  });
});
