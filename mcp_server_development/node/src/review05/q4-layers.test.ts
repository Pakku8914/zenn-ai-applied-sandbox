/**
 * 失敗がどの層に出るかを検算する（問題4）
 *
 *   docker compose exec node npx vitest run src/review05/q4-layers.test.ts
 */
import { describe, expect, it } from "vitest";

import { createGateServer, type Scope } from "./gate-server.js";
import { callTool, connectInMemory, failureText } from "./harness.js";

async function connect(scopes: readonly Scope[]) {
  return connectInMemory(
    createGateServer({ scopes, audit: () => {}, nonce: () => "deadbeefdeadbeef" }),
  );
}

describe("① スキーマ層 ―― SDK が引数を検証する", () => {
  const cases: [string, string, Record<string, unknown>][] = [
    ["limit が下限未満", "search_requests", { limit: 0 }],
    ["limit が上限超過", "search_requests", { limit: 99 }],
    ["query の型が違う", "search_requests", { query: 123 }],
    ["id が書式に合わない", "get_request", { id: "../etc/passwd" }],
  ];

  it.each(cases)("%s → 例外にならず isError で返る", async (_label, tool, args) => {
    const client = await connect(["requests:read"]);

    // ★ await した結果が返ってくる（throw されない）
    const message = failureText(await callTool(client, tool, args));

    expect(message).toContain("-32602");
    // 層の決め手はコードではなくこの語（未知のツール名でも -32602 は出る）
    expect(message).toContain(`Invalid arguments for tool ${tool}`);
    await client.close();
  });
});

describe("② ツール実行層 ―― ディスパッチ・ドメイン・認可", () => {
  it("存在しないツール名も isError で返る", async () => {
    const client = await connect(["requests:read"]);
    const message = failureText(await callTool(client, "approve_everything", {}));

    expect(message).toContain("Tool approve_everything not found");
    // -32602 は入るが、スキーマ層とは別の失敗である
    expect(message).not.toContain("Invalid arguments for tool");
    await client.close();
  });

  it("存在しない申請ID はドメイン層の失敗", async () => {
    const client = await connect(["requests:read"]);
    const message = failureText(await callTool(client, "get_request", { id: "req-9999" }));

    expect(message).toContain("指定された申請が見つかりません");
    expect(message).toContain("search_requests"); // 回復方法が書かれている
    expect(message).not.toContain("-32602");
    await client.close();
  });

  it("スコープ不足は認可層の失敗（必要なスコープ名が文面に入る）", async () => {
    const client = await connect(["requests:read"]);
    const message = failureText(
      await callTool(client, "decide_request", { id: "req-1001", decision: "approve" }),
    );

    expect(message).toContain("requests:approve");
    expect(message).not.toContain("-32602");
    await client.close();
  });

  it("決裁できない状態もドメイン層の失敗", async () => {
    const client = await connect(["requests:read", "requests:approve"]);
    const message = failureText(
      await callTool(client, "decide_request", {
        id: "req-1002",
        decision: "approve",
        confirm: true,
      }),
    );

    expect(message).toContain("既に approved");
    expect(message).not.toContain("-32602");
    await client.close();
  });
});

describe("③ 本物の JSON-RPC エラー", () => {
  it("prompts/get の失敗は -32602 として reject される", async () => {
    const client = await connect(["requests:read"]);

    // isError はツール専用の仕組み。プロンプトの失敗は JSON-RPC エラーになる
    await expect(
      client.getPrompt({ name: "draft_reply", arguments: { id: "req-9999" } }),
    ).rejects.toMatchObject({ code: -32602 });
    await client.close();
  });

  it("宣言していないケイパビリティは、クライアントが送信前に落とす", async () => {
    const client = await connect(["requests:read"]);

    // サーバーは resources を登録していないので capabilities に載らない。
    // 文面は SDK の版で変わりうるので、reject されることだけを固定する
    await expect(client.listResources()).rejects.toThrow();
    await client.close();
  });
});
