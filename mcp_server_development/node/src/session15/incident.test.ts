import { describe, expect, it } from "vitest";

import { findImpact, percentile95, summarizeAuditLog } from "./incident.js";

function record(
  index: number,
  overrides: Record<string, unknown>,
): string {
  return JSON.stringify({
    ts: `2026-08-05T00:00:0${index}.000Z`,
    server: "docsearch-guarded",
    tenantId: "acme",
    subject: "subject-a",
    sessionRef: "session-a",
    event: "tool_call",
    target: "search_documents",
    outcome: "ok",
    params: {},
    ...overrides,
  });
}

/** 有効 8 行 ＋ 壊れた 1 行 */
const LINES = [
  record(1, { durationMs: 5, findings: [] }),
  record(2, { durationMs: 7, findings: ["override_instructions"] }),
  record(3, { durationMs: 3, event: "resource_read", target: "docs://" }),
  record(4, { durationMs: 4, event: "prompt_get", target: "summarize_search", findings: ["override_instructions"] }),
  record(5, { durationMs: 6, subject: "subject-b", sessionRef: "session-b" }),
  record(6, {
    durationMs: 1,
    event: "resource_read",
    target: "docs://",
    outcome: "rejected",
    reason: "parent_traversal",
    subject: "subject-b",
    sessionRef: "session-b",
  }),
  record(7, {
    durationMs: 2,
    outcome: "rejected",
    reason: "invalid_arguments",
    subject: "subject-b",
    sessionRef: "session-b",
  }),
  record(8, {
    durationMs: 9,
    event: "resource_read",
    target: "docs://",
    outcome: "error",
    reason: "unexpected",
    subject: "subject-b",
    sessionRef: "session-b",
  }),
  "{ これは壊れた行です",
];

describe("summarizeAuditLog", () => {
  const summary = summarizeAuditLog(LINES);

  it("行数と壊れた行を数える", () => {
    expect(summary.total).toBe(9);
    expect(summary.malformed).toBe(1);
  });

  it("結果ごとの件数を数える", () => {
    expect(summary.byOutcome).toEqual({ error: 1, ok: 5, rejected: 2 });
  });

  it("対象ごとの件数をキー昇順で返す", () => {
    expect(Object.keys(summary.byTarget)).toEqual([
      "docs://",
      "search_documents",
      "summarize_search",
    ]);
    expect(summary.byTarget["docs://"]).toBe(3);
  });

  it("拒否理由を数える", () => {
    expect(summary.byReason).toEqual({
      invalid_arguments: 1,
      parent_traversal: 1,
      unexpected: 1,
    });
  });

  it("指示文の検出件数とエラー率を出す", () => {
    expect(summary.directiveHits).toBe(2);
    expect(summary.errorRate).toBe(0.375); // (8 - 5) / 8
  });

  it("p95 は最近傍順位法で求める", () => {
    // durationMs をソートすると [1,2,3,4,5,6,7,9]。ceil(0.95 * 8) - 1 = 7 → 9
    expect(summary.p95Ms).toBe(9);
  });

  it("空の入力でも例外にならない", () => {
    const empty = summarizeAuditLog([]);
    expect(empty.total).toBe(0);
    expect(empty.errorRate).toBe(0);
    expect(empty.p95Ms).toBe(0);
  });
});

describe("percentile95", () => {
  it("1 件なら唯一の値", () => {
    expect(percentile95([42])).toBe(42);
  });

  it("20 件なら 19 番目（0 始まり）", () => {
    const values = Array.from({ length: 20 }, (_, index) => index + 1);
    expect(percentile95(values)).toBe(19);
  });
});

describe("findImpact", () => {
  it("指示文の検出で絞ると、影響したセッションと期間が分かる", () => {
    const impact = findImpact(LINES, { directiveId: "override_instructions" });
    expect(impact.calls).toBe(2);
    expect(impact.sessions).toEqual(["session-a"]);
    expect(impact.tenants).toEqual(["acme"]);
    expect(impact.targets).toEqual(["search_documents", "summarize_search"]);
    expect(impact.firstSeen).toBe("2026-08-05T00:00:02.000Z");
    expect(impact.lastSeen).toBe("2026-08-05T00:00:04.000Z");
  });

  it("利用者の参照値で絞れる（生の識別子は要らない）", () => {
    const impact = findImpact(LINES, { subject: "subject-b" });
    expect(impact.calls).toBe(4);
    expect(impact.sessions).toEqual(["session-b"]);
  });

  it("時刻で絞れる（ISO 8601 の辞書順比較）", () => {
    const impact = findImpact(LINES, { since: "2026-08-05T00:00:06.000Z" });
    expect(impact.calls).toBe(3);
  });

  it("該当なしでも例外にならない", () => {
    const impact = findImpact(LINES, { directiveId: "role_override" });
    expect(impact.calls).toBe(0);
    expect(impact.firstSeen).toBeUndefined();
  });
});
