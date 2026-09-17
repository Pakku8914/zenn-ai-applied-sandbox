/**
 * キャンセルとタイムアウトのテスト（問題5 の解答）
 *
 *   docker compose exec node npx vitest run src/session13/cancel.test.ts
 *
 * 確かめるのは「クライアントが待つのをやめたこと」ではなく
 * 「サーバー側の処理が実際に止まったこと」です。前者だけを見ていると、
 * セッション8 の Bad 実装（キャンセル通知を受けても走り続ける）を検出できません。
 */
import { beforeEach, describe, expect, it } from "vitest";

import { cancelledTasks, createFixtureServer, resetCancelledTasks } from "./fixture-server.js";
import { callTool, connectInMemory, toolText, waitFor } from "./harness.js";

describe("キャンセルとタイムアウト", () => {
  beforeEach(() => {
    // 記録を持ち越すと、前のテストの結果で通ってしまう（偽の緑）
    resetCancelledTasks();
  });

  it("AbortSignal で中断すると、サーバー側も処理を止める", async () => {
    const client = await connectInMemory(createFixtureServer());
    const controller = new AbortController();
    const pending = callTool(
      client,
      "slow_task",
      { taskId: "t-cancel", ms: 3000 },
      { signal: controller.signal },
    );

    // 処理が始まる前に中断すると「開始前に捨てられた」経路になり、
    // ハンドラの signal 監視を検証できない
    await new Promise((resolve) => setTimeout(resolve, 50));
    controller.abort(new Error("テストから中断しました"));

    await expect(pending).rejects.toThrow();
    // ★ ここが本番。通知が届いてハンドラが次に aborted を見るまで数ミリ秒かかるので待つ
    await waitFor(() => cancelledTasks().includes("t-cancel"));
    expect(cancelledTasks()).toEqual(["t-cancel"]);
    await client.close();
  });

  it("timeout を過ぎるとクライアント側が呼び出しを打ち切る", async () => {
    const client = await connectInMemory(createFixtureServer());
    const pending = callTool(client, "slow_task", { taskId: "t-timeout", ms: 800 }, { timeout: 100 });

    // タイムアウトはクライアント側の都合。サーバーが止まる保証は無いので、
    // ここではサーバー側の停止を期待しない（サーバー側の上限は自分で持つ・セッション8）
    await expect(pending).rejects.toThrow(/-32001|timed out/i);
    await client.close();
  });

  it("時間内に終わる処理は普通に成功する", async () => {
    const client = await connectInMemory(createFixtureServer());
    const result = await callTool(client, "slow_task", { taskId: "t-fast", ms: 20 });

    expect(result.isError ?? false).toBe(false);
    expect(toolText(result)).toBe("t-fast を 20ms で完了しました");
    // 「空であること」ではなく「この taskId が入っていないこと」を見ます。
    // 直前のタイムアウトのテストで走らせた処理はサーバー側でまだ動いており、
    // beforeEach のリセット後に中断が記録されることがあるためです
    // （クライアントのタイムアウトはサーバーを止めない ―― セッション7・8 の論点）
    expect(cancelledTasks()).not.toContain("t-fast");
    await client.close();
  });
});
