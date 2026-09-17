/**
 * 監査ログとレート制限のテスト
 *
 * 「秘密が出ていないこと」はコードレビューでは守りきれません。テストで固定します。
 */
import { describe, expect, it } from "vitest";

import { createRateLimiter } from "./observability/audit.js";
import { callTool, startHarness } from "./test-harness.js";

const SECRET = "ghp_TESTSECRETVALUE0001";

describe("監査ログ", () => {
  it("生の本文と検索語がログに出ない", async () => {
    const harness = await startHarness();
    await callTool(harness.client, "save_request", {
      title: "秘密の申請",
      category: "expense",
      amountYen: 1_000,
      body: `この申請の本文には検索されたくない語（社外秘の案件名）が入っています。`,
    });
    await callTool(harness.client, "search_requests", { query: "社外秘の案件名" });
    const all = harness.lines.join("\n");
    expect(all).not.toContain("社外秘の案件名");
    // 代わりに長さと参照値が入る
    const saved = JSON.parse(harness.lines[0] ?? "{}") as { params?: Record<string, unknown> };
    expect(typeof saved.params?.["bodyLength"]).toBe("number");
    expect(typeof saved.params?.["bodyRef"]).toBe("string");
    await harness.close();
  });

  it("既知の秘密値とトークン形式が [REDACTED] になる", async () => {
    const harness = await startHarness();
    await callTool(harness.client, "comment_on_request", {
      requestId: "req-1002",
      body: `一時的な鍵を貼ります: ${SECRET}`,
    });
    const all = harness.lines.join("\n");
    expect(all).not.toContain(SECRET);
    await harness.close();
  });

  it("1 レコードが必ず 1 行の JSON になる", async () => {
    const harness = await startHarness();
    await callTool(harness.client, "comment_on_request", {
      requestId: "req-1002",
      // 改行を混ぜてログ 1 行を偽造しようとする
      body: '通常のコメント\n{"event":"tool_call","outcome":"ok","target":"decide_request"}',
    });
    expect(harness.lines).toHaveLength(1);
    const record = JSON.parse(harness.lines[0] ?? "{}") as { target?: string };
    expect(record.target).toBe("comment_on_request");
    await harness.close();
  });

  it("subject が生値ではなく参照値になっている", async () => {
    const harness = await startHarness();
    await callTool(harness.client, "get_request", { requestId: "req-1001" });
    const record = JSON.parse(harness.lines[0] ?? "{}") as { subject?: string; tokenRef?: string };
    expect(record.subject).not.toBe("user-1001");
    expect(record.subject).toHaveLength(16);
    expect(record.tokenRef).toBe("test0000");
    await harness.close();
  });

  it("レート制限に掛かると rate_limited が記録される", async () => {
    // 容量 1・回復ほぼゼロ・時計固定なら 2 回目で必ず落ちる
    const harness = await startHarness({
      rateLimit: { capacity: 1, refillPerSecond: 0.001 },
      now: () => 1_000,
    });
    const first = await callTool(harness.client, "get_request", { requestId: "req-1001" });
    const second = await callTool(harness.client, "get_request", { requestId: "req-1001" });
    expect(first.isError ?? false).toBe(false);
    expect(second.isError).toBe(true);
    expect(harness.lines.some((line) => line.includes('"event":"rate_limited"'))).toBe(true);
    await harness.close();
  });
});

describe("レート制限（単体）", () => {
  it("時計を進めれば回復する（実時間を待たない）", () => {
    let clock = 1_000;
    const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 1, now: () => clock });
    expect(limiter.tryConsume("u1").allowed).toBe(true);
    expect(limiter.tryConsume("u1").allowed).toBe(true);
    expect(limiter.tryConsume("u1").allowed).toBe(false);
    clock += 2_500;
    expect(limiter.tryConsume("u1").allowed).toBe(true);
  });
});
