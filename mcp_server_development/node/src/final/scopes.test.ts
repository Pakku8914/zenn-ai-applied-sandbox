/**
 * 認可のテスト（HTTP を起動せず、認証文脈を注入して確かめる）
 *
 * 異常系は rejects ではなく isError で書きます。SDK 1.30.0 の callTool() は
 * 引数違反も未知のツール名も例外にせず、isError のツール結果として返します。
 */
import { describe, expect, it } from "vitest";

import { SCOPE_APPROVE, SCOPE_READ, SCOPE_WRITE } from "./auth/scopes.js";
import { callTool, startHarness, textOf } from "./test-harness.js";

describe("スコープの分離", () => {
  it("requests:read だけでは decide_request が forbidden", async () => {
    const harness = await startHarness({ scopes: [SCOPE_READ] });
    const result = await callTool(harness.client, "decide_request", {
      requestId: "req-1002",
      decision: "approve",
    });
    expect(result.isError).toBe(true);
    const text = textOf(result);
    expect(text).toContain("[forbidden]");
    expect(text).toContain("requests:approve");
    // 「代わりに何ができるか」まで伝える
    expect(text).toContain("comment_on_request");
    await harness.close();
  });

  it("requests:write でも decide_request は通らない", async () => {
    const harness = await startHarness({ scopes: [SCOPE_READ, SCOPE_WRITE] });
    const denied = await callTool(harness.client, "decide_request", {
      requestId: "req-1002",
      decision: "approve",
    });
    expect(denied.isError).toBe(true);
    // 同じトークンで save_request は通る
    const allowed = await callTool(harness.client, "save_request", {
      requestId: "req-1001",
      amountYen: 13_000,
    });
    expect(allowed.isError ?? false).toBe(false);
    await harness.close();
  });

  it("requests:approve があればドライランが通る", async () => {
    const harness = await startHarness({ scopes: [SCOPE_READ, SCOPE_APPROVE] });
    const result = await callTool(harness.client, "decide_request", {
      requestId: "req-1002",
      decision: "approve",
    });
    expect(result.isError ?? false).toBe(false);
    expect(result.structuredContent?.["applied"]).toBe(false);
    await harness.close();
  });

  it("スコープが 1 つも無ければ全ツールが forbidden（fail closed）", async () => {
    const harness = await startHarness({ scopes: [] });
    for (const name of ["search_requests", "get_request", "save_request"]) {
      const result = await callTool(harness.client, name, { requestId: "req-1001" });
      expect(result.isError, name).toBe(true);
      expect(textOf(result)).toContain("[forbidden]");
    }
    await harness.close();
  });

  it("引数違反と未知のツール名は例外ではなく isError で返る", async () => {
    const harness = await startHarness();
    const badEnum = await callTool(harness.client, "search_requests", { status: ["reviewing"] });
    expect(badEnum.isError).toBe(true);
    expect(textOf(badEnum)).toContain("-32602");

    const unknown = await callTool(harness.client, "approve_request", {});
    expect(unknown.isError).toBe(true);
    expect(textOf(unknown)).toContain("not found");
    await harness.close();
  });
});
