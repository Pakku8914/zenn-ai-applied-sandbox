/**
 * 異常系の契約テスト
 *
 *   docker compose exec node npx vitest run src/session13/errors.test.ts
 *
 * MCP の異常系は「例外」ではなく「isError の付いた正常なレスポンス」で届きます。
 * ここを取り違えると、テストは書けているのに何も検証していない状態になります。
 */
import { describe, expect, it } from "vitest";

import {
  LATEST_PROTOCOL_VERSION,
  SUPPORTED_PROTOCOL_VERSIONS,
} from "@modelcontextprotocol/sdk/types.js";

import { createFixtureServer } from "./fixture-server.js";
import { callTool, connectInMemory, expectToolFailure, rawSession, resultOf, toolText } from "./harness.js";

describe("① 引数のスキーマ違反はツール実行の失敗として届く", () => {
  // 仕様の表をそのままテストケースにする（受け入れ条件とテストが 1 対 1 になる）
  const invalidArguments: [string, Record<string, unknown>][] = [
    ["必須引数が無い", {}],
    ["型が違う", { text: 123 }],
    ["最小長を下回る", { text: "" }],
    ["上限を超える", { text: "あ", count: 99 }],
    ["整数ではない", { text: "あ", count: 1.5 }],
  ];

  it.each(invalidArguments)("%s → isError で返る（例外にならない）", async (_label, args) => {
    const client = await connectInMemory(createFixtureServer());

    // ★ ここが本節の核心。await した結果が返ってくる（throw されない）
    const result = await callTool(client, "echo_text", args);

    const message = expectToolFailure(result);
    expect(message).toContain("-32602");
    expect(message).toContain("Invalid arguments for tool echo_text");
    // 失敗時は structuredContent を返さない（outputSchema の検証もスキップされる）
    expect(result.structuredContent).toBeUndefined();
    await client.close();
  });
});

describe("② 存在しないツール", () => {
  it("未知のツール名も isError で返る", async () => {
    const client = await connectInMemory(createFixtureServer());
    const message = expectToolFailure(await callTool(client, "no_such_tool", {}));
    expect(message).toContain("Tool no_such_tool not found");
    await client.close();
  });
});

describe("③ 宣言していない引数は黙って捨てられる", () => {
  it("未知のキーを足しても成功する（既定のスキーマは厳格ではない）", async () => {
    const client = await connectInMemory(createFixtureServer());
    const result = await callTool(client, "echo_text", { text: "こんにちは", unknownKey: 1 });

    // 「送っても無視される」= 引数名の間違いに気づけない、という意味でもある
    expect(result.isError ?? false).toBe(false);
    expect(toolText(result)).toBe("こんにちは");
    await client.close();
  });
});

describe("④ 本物の JSON-RPC エラーになるのは「そのメソッドを受け付けられないとき」", () => {
  it("宣言していないケイパビリティのメソッドは -32601 を返す", async () => {
    const session = await rawSession(createFixtureServer());

    const response = await session.request("resources/list", {});

    expect(response["result"]).toBeUndefined();
    expect(response["error"]).toMatchObject({ code: -32601, message: "Method not found" });
    await session.close();
  });

  it("initialize の capabilities に resources が載っていない", async () => {
    const session = await rawSession(createFixtureServer());
    const capabilities = resultOf(session.initializeResponse)["capabilities"];

    expect(capabilities).toEqual({ tools: { listChanged: true } });
    await session.close();
  });

  it("対応済みの古いプロトコル版を提示すると、その版で合意する", async () => {
    const oldest = SUPPORTED_PROTOCOL_VERSIONS[SUPPORTED_PROTOCOL_VERSIONS.length - 1];
    expect(typeof oldest).toBe("string");

    const session = await rawSession(createFixtureServer(), { protocolVersion: oldest });

    expect(resultOf(session.initializeResponse)["protocolVersion"]).toBe(oldest);
    await session.close();
  });

  it("知らない版を提示するとサーバーの最新版が返る（エラーにはならない）", async () => {
    const session = await rawSession(createFixtureServer(), { protocolVersion: "2099-01-01" });

    expect(resultOf(session.initializeResponse)["protocolVersion"]).toBe(LATEST_PROTOCOL_VERSION);
    await session.close();
  });
});
