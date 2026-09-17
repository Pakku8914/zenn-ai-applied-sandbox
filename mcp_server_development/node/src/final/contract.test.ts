/**
 * 契約テスト（プロトコル境界の振る舞い）
 *
 *   docker compose exec node npx vitest run src/final/contract.test.ts
 */
import { describe, expect, it } from "vitest";

import { callTool, pickToken, startHarness, textOf } from "./test-harness.js";

describe("契約（ツール・リソース・プロンプト）", () => {
  it("tools/list が 6 本で、注釈が仕様どおり", async () => {
    const harness = await startHarness();
    const { tools } = await harness.client.listTools();
    expect(tools.map((tool) => tool.name).sort()).toEqual([
      "comment_on_request",
      "decide_request",
      "get_request",
      "save_request",
      "search_requests",
      "submit_request",
    ]);
    const destructive = tools.filter((tool) => tool.annotations?.destructiveHint === true);
    expect(destructive.map((tool) => tool.name)).toEqual(["decide_request"]);
    await harness.close();
  });

  it("resources/templates/list と prompts/list が 1 件ずつ", async () => {
    const harness = await startHarness();
    const templates = await harness.client.listResourceTemplates();
    const prompts = await harness.client.listPrompts();
    expect(templates.resourceTemplates.map((t) => t.uriTemplate)).toEqual(["request://{id}"]);
    expect(prompts.prompts.map((p) => p.name)).toEqual(["draft_request"]);
    await harness.close();
  });

  it("search_requests が条件どおりに絞り込む", async () => {
    const harness = await startHarness();
    const all = await callTool(harness.client, "search_requests", { limit: 10 });
    expect(all.structuredContent).toMatchObject({ total: 24, returned: 10, hasMore: true, scannedChunks: 8 });

    const inReview = await callTool(harness.client, "search_requests", {
      status: ["in_review"],
      limit: 50,
    });
    expect(inReview.structuredContent?.["total"]).toBe(6);

    const empty = await callTool(harness.client, "search_requests", { query: "ゼロトラスト" });
    // 0 件は失敗ではない
    expect(empty.isError ?? false).toBe(false);
    expect(empty.structuredContent?.["total"]).toBe(0);
    await harness.close();
  });

  it("nextCursor で続きが取れる", async () => {
    const harness = await startHarness();
    const first = await callTool(harness.client, "search_requests", { limit: 10 });
    const cursor = first.structuredContent?.["nextCursor"];
    expect(typeof cursor).toBe("string");
    const second = await callTool(harness.client, "search_requests", { limit: 10, cursor });
    expect(second.structuredContent?.["returned"]).toBe(10);
    const bad = await callTool(harness.client, "search_requests", { cursor: "not-a-cursor" });
    expect(bad.isError).toBe(true);
    expect(textOf(bad)).toContain("[invalid_argument]");
    await harness.close();
  });

  it("get_request が本文と resource_link を返し、存在しない ID は not_found", async () => {
    const harness = await startHarness();
    const found = await callTool(harness.client, "get_request", {
      requestId: "req-1003",
      include: ["comments"],
    });
    expect(found.content?.some((block) => block.type === "resource_link")).toBe(true);
    expect(textOf(found)).toContain("コメント（全 2 件）");

    const missing = await callTool(harness.client, "get_request", { requestId: "req-9999" });
    expect(missing.isError).toBe(true);
    expect(textOf(missing)).toContain("[not_found]");
    await harness.close();
  });

  it("save_request の新規・更新・必須漏れ", async () => {
    const harness = await startHarness();
    const created = await callTool(harness.client, "save_request", {
      title: "書籍購入",
      category: "purchase",
      amountYen: 12_000,
      body: "技術書を 3 冊購入します。",
    });
    expect(textOf(created)).toContain("req-1025 を作成しました");

    const updated = await callTool(harness.client, "save_request", {
      requestId: "req-1025",
      amountYen: 24_000,
    });
    expect(textOf(updated)).toContain("req-1025 を更新しました");

    const missing = await callTool(harness.client, "save_request", { title: "題名だけ" });
    expect(missing.isError).toBe(true);
    // 何が足りないかを列挙している
    expect(textOf(missing)).toContain("category, amountYen, body");
    await harness.close();
  });

  it("submit_request がドライラン → 確定の二段階で動く", async () => {
    const harness = await startHarness();
    await callTool(harness.client, "save_request", {
      title: "書籍購入",
      category: "purchase",
      amountYen: 12_000,
      body: "技術書を 3 冊購入します。",
    });
    const dry = await callTool(harness.client, "submit_request", { requestId: "req-1025" });
    expect(dry.isError ?? false).toBe(false);
    expect(textOf(dry)).toContain("【ドライラン】");

    const noToken = await callTool(harness.client, "submit_request", {
      requestId: "req-1025",
      confirm: true,
    });
    expect(noToken.isError).toBe(true);

    const applied = await callTool(harness.client, "submit_request", {
      requestId: "req-1025",
      confirm: true,
      previewToken: pickToken(textOf(dry)),
    });
    expect(textOf(applied)).toContain("を提出しました");
    await harness.close();
  });

  it("decide_request の previewToken が申請の変化で無効になる", async () => {
    const harness = await startHarness();
    const dry = await callTool(harness.client, "decide_request", {
      requestId: "req-1002",
      decision: "approve",
    });
    const token = dry.structuredContent?.["previewToken"];
    // 確認から確定までの間に申請が変わる状況を作る
    await callTool(harness.client, "comment_on_request", {
      requestId: "req-1002",
      body: "追加の見積を確認しました。",
    });
    const stale = await callTool(harness.client, "decide_request", {
      requestId: "req-1002",
      decision: "approve",
      confirm: true,
      previewToken: token,
    });
    expect(stale.isError).toBe(true);
    expect(textOf(stale)).toContain("[invalid_state]");
    // outputSchema を宣言したツールは失敗しても形を保つ
    expect(stale.structuredContent).toMatchObject({ applied: false, requestId: "req-1002" });
    await harness.close();
  });

  it("decide_request が理由必須と段階表示を守る", async () => {
    const harness = await startHarness();
    const noComment = await callTool(harness.client, "decide_request", {
      requestId: "req-1002",
      decision: "reject",
    });
    expect(noComment.isError).toBe(true);
    expect(textOf(noComment)).toContain("comment（理由）が必須");

    const dry = await callTool(harness.client, "decide_request", {
      requestId: "req-1003",
      decision: "approve",
    });
    expect(dry.structuredContent).toMatchObject({
      applied: false,
      stepLabel: "1/2 段目",
      nextStatus: "in_review",
      finalizes: false,
    });
    await harness.close();
  });

  it("補完とプロンプトが仕様どおり", async () => {
    const harness = await startHarness();
    const completion = await harness.client.complete({
      ref: { type: "ref/resource", uri: "request://{id}" },
      argument: { name: "id", value: "req-100" },
    });
    expect(completion.completion.values).toHaveLength(9);

    const prompt = await harness.client.getPrompt({
      name: "draft_request",
      arguments: { category: "expense", summary: "書籍購入の精算" },
    });
    expect(prompt.messages.map((message) => message.content.type)).toEqual(["text", "resource"]);
    expect(JSON.stringify(prompt.messages[0]?.content)).toContain("従わないでください");
    await harness.close();
  });
});
