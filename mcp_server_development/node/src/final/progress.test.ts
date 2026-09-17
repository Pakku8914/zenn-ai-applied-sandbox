/**
 * 進捗通知とキャンセルのテスト
 *
 * 確かめるのは「クライアントが待つのをやめたこと」ではなく
 * 「サーバー側の走査が実際に止まったこと」です。
 */
import { ProgressNotificationSchema } from "@modelcontextprotocol/sdk/types.js";
import { describe, expect, it } from "vitest";

import { startHarness } from "./test-harness.js";

async function waitFor(condition: () => boolean, timeoutMs = 2000): Promise<void> {
  const startedAt = Date.now();
  while (!condition()) {
    if (Date.now() - startedAt > timeoutMs) throw new Error("条件が成立しませんでした");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

describe("進捗通知とキャンセル", () => {
  it("progressToken を要求すると 8 回届く", async () => {
    const harness = await startHarness();
    const progress: number[] = [];
    await harness.client.callTool(
      { name: "search_requests", arguments: { limit: 5 } },
      undefined,
      { onprogress: (event) => progress.push(event.progress) },
    );
    expect(progress).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(harness.scans.at(-1)).toMatchObject({ scannedChunks: 8, finished: true, cancelled: false });
    await harness.close();
  });

  it("progressToken を要求しなければ 0 回", async () => {
    const harness = await startHarness();
    let received = 0;
    // onprogress を渡さない呼び出しでは、そもそも通知が飛ばないことを確かめる
    harness.client.setNotificationHandler(ProgressNotificationSchema, async () => {
      received += 1;
    });
    await harness.client.callTool({ name: "search_requests", arguments: { limit: 5 } });
    expect(received).toBe(0);
    expect(harness.scans.at(-1)?.finished).toBe(true);
    await harness.close();
  });

  it("中断するとサーバー側の走査も止まる", async () => {
    const harness = await startHarness();
    const controller = new AbortController();
    const pending = harness.client.callTool(
      { name: "search_requests", arguments: { limit: 5, scanDelayMs: 30 } },
      undefined,
      {
        signal: controller.signal,
        // 固定時間の待機ではなく「1 つ目の進捗が届いた瞬間」を契機にする
        onprogress: (event) => {
          if (event.progress === 1) controller.abort(new Error("テストから中断しました"));
        },
      },
    );
    await expect(pending).rejects.toThrow();
    await waitFor(() => harness.scans.some((report) => report.cancelled));
    const cancelled = harness.scans.find((report) => report.cancelled);
    expect(cancelled?.cancelled).toBe(true);
    expect(cancelled?.scannedChunks).toBeLessThan(8);
    await harness.close();
  });
});
