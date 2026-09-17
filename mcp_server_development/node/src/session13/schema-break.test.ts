/**
 * 「スナップショットが破壊的変更を検出できること」のテスト（問題4-b の解答）
 *
 *   docker compose exec node npx vitest run src/session13/schema-break.test.ts
 *
 * テストのためのテストですが、価値があります。ダイジェストの作り方を間違えて
 * 「引数名を見ていない」実装になっていたら、この 2 件が教えてくれます。
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { describe, expect, it } from "vitest";

import { createBrokenFixtureServer } from "./broken-fixture-server.js";
import { createFixtureServer } from "./fixture-server.js";
import { connectInMemory } from "./harness.js";
import { compareStrings, digestTools, type ToolDigest } from "./schema-digest.js";

/** 正しい契約（fixture-server.ts の echo_text） */
const EXPECTED_DIGEST: ToolDigest[] = [
  {
    name: "echo_text",
    title: "テキストのエコー",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    args: [
      { name: "count", required: false, hasDescription: true },
      { name: "text", required: true, hasDescription: true },
    ],
  },
  {
    name: "fail_always",
    title: "必ず失敗する処理",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    args: [{ name: "reason", required: true, hasDescription: true }],
  },
  {
    name: "slow_task",
    title: "時間のかかる処理",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    args: [
      { name: "ms", required: true, hasDescription: true },
      { name: "taskId", required: true, hasDescription: true },
    ],
  },
];

async function digestOf(server: McpServer): Promise<ToolDigest[]> {
  const client = await connectInMemory(server);
  const { tools } = await client.listTools();
  await client.close();
  return digestTools(tools);
}

/**
 * ダイジェストの差分を、人が読める 1 行ずつに落とす。
 * 「落ちた」だけでは判断できず、「何が変わったか」まで出せると
 * レビューで「これは破壊的変更か」を議論できます。
 */
export function diffDigests(
  expected: readonly ToolDigest[],
  actual: readonly ToolDigest[],
): string[] {
  const lines: string[] = [];
  const names = [
    ...new Set([...expected.map((tool) => tool.name), ...actual.map((tool) => tool.name)]),
  ].sort(compareStrings);

  for (const name of names) {
    const before = expected.find((tool) => tool.name === name);
    const after = actual.find((tool) => tool.name === name);
    if (before === undefined) {
      lines.push(`${name}: ツールが追加されました`);
      continue;
    }
    if (after === undefined) {
      lines.push(`${name}: ツールが削除されました`);
      continue;
    }

    const beforeArgs = before.args.map((arg) => arg.name);
    const afterArgs = after.args.map((arg) => arg.name);
    for (const added of afterArgs.filter((arg) => !beforeArgs.includes(arg))) {
      lines.push(`${name}: 引数 ${added} が追加されました`);
    }
    for (const removed of beforeArgs.filter((arg) => !afterArgs.includes(arg))) {
      lines.push(`${name}: 引数 ${removed} が削除されました`);
    }
    for (const arg of after.args) {
      const same = before.args.find((candidate) => candidate.name === arg.name);
      if (same !== undefined && same.required !== arg.required) {
        lines.push(`${name}: 引数 ${arg.name} の必須が ${same.required} → ${arg.required} に変わりました`);
      }
    }
  }

  // 出力の順序を固定する（テストの期待値を書けるようにするため）
  return lines.sort(compareStrings);
}

describe("スナップショットが破壊的変更を検出できる", () => {
  it("正しい実装はダイジェストと一致する", async () => {
    expect(await digestOf(createFixtureServer())).toEqual(EXPECTED_DIGEST);
  });

  it("引数名を変えた複製は検出され、差分を説明できる", async () => {
    const broken = await digestOf(createBrokenFixtureServer());

    expect(broken).not.toEqual(EXPECTED_DIGEST);

    // 壊した複製は echo_text だけを持つサーバーなので、差分も echo_text に絞って比べます。
    // 全体と比べると「他の 2 本が削除された」という別の差分が混ざり、
    // 何が壊れたのかが読み取りにくくなります
    const echoOnly = EXPECTED_DIGEST.filter((tool) => tool.name === "echo_text");
    expect(diffDigests(echoOnly, broken)).toEqual([
      "echo_text: 引数 message が追加されました",
      "echo_text: 引数 text が削除されました",
    ]);
  });
});
