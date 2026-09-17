/**
 * スキーマの回帰テスト（2 段構え）
 *
 *   ① 正規化ダイジェストを、テストに手で書いた期待値と比較する（意図の宣言）
 *   ② 生の tools/list をベースラインファイルと比較する（SDK 由来の変化まで検出）
 *
 * CI では SNAPSHOT_CI=1 を立て、ベースラインが無いこと自体を失敗にします。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { startHarness } from "./test-harness.js";

const SNAPSHOT_DIR = path.resolve("src/final/__snapshots__");

type ArgumentDigest = { name: string; required: boolean; hasDescription: boolean };
type ToolDigest = {
  name: string;
  annotations: Record<string, boolean | null>;
  args: ArgumentDigest[];
};

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function digest(tools: readonly unknown[]): ToolDigest[] {
  return tools
    .map((tool) => {
      const record = tool as Record<string, unknown>;
      const schema = (record["inputSchema"] ?? {}) as Record<string, unknown>;
      const properties = (schema["properties"] ?? {}) as Record<string, unknown>;
      const required = new Set((schema["required"] ?? []) as string[]);
      const annotations = (record["annotations"] ?? {}) as Record<string, unknown>;
      return {
        name: String(record["name"]),
        annotations: {
          readOnlyHint: (annotations["readOnlyHint"] as boolean | undefined) ?? null,
          destructiveHint: (annotations["destructiveHint"] as boolean | undefined) ?? null,
          idempotentHint: (annotations["idempotentHint"] as boolean | undefined) ?? null,
          openWorldHint: (annotations["openWorldHint"] as boolean | undefined) ?? null,
        },
        args: Object.keys(properties)
          .sort(compare)
          .map((name) => ({
            name,
            required: required.has(name),
            // 文面そのものは比較しない（推敲で落ちないように）
            hasDescription:
              typeof (properties[name] as Record<string, unknown>)["description"] === "string",
          })),
      };
    })
    .sort((left, right) => compare(left.name, right.name));
}

/** ★ これが「守ると宣言した契約」。引数名を 1 文字変えたら赤くなる */
const EXPECTED_ARGS: Readonly<Record<string, string[]>> = {
  comment_on_request: ["body", "links", "requestId"],
  decide_request: ["comment", "confirm", "decision", "previewToken", "requestId"],
  get_request: ["include", "requestId"],
  save_request: ["amountYen", "body", "category", "requestId", "title"],
  search_requests: [
    "applicantId",
    "category",
    "cursor",
    "limit",
    "minAmountYen",
    "query",
    "scanDelayMs",
    "status",
  ],
  submit_request: ["confirm", "previewToken", "requestId"],
};

describe("スキーマの回帰", () => {
  it("引数名・必須・注釈が契約どおり", async () => {
    const harness = await startHarness();
    const { tools } = await harness.client.listTools();
    const digested = digest(tools);

    expect(Object.fromEntries(digested.map((tool) => [tool.name, tool.args.map((a) => a.name)]))).toEqual(
      EXPECTED_ARGS,
    );
    // 説明の無い引数を 1 つも作らない
    expect(digested.every((tool) => tool.args.every((arg) => arg.hasDescription))).toBe(true);
    // 注釈 4 つを全ツールで明示している（null が 1 つも無い）
    expect(
      digested.every((tool) => Object.values(tool.annotations).every((value) => value !== null)),
    ).toBe(true);
    expect(digested.find((tool) => tool.name === "decide_request")?.annotations.destructiveHint).toBe(
      true,
    );
    await harness.close();
  });

  it("生の tools/list がベースラインと一致する", async () => {
    const harness = await startHarness();
    const { tools } = await harness.client.listTools();
    await harness.close();

    fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });
    const file = path.join(SNAPSHOT_DIR, "tools-list.json");
    if (!fs.existsSync(file)) {
      if (process.env["SNAPSHOT_CI"] === "1") {
        throw new Error("ベースラインがありません。ローカルで生成してコミットしてください。");
      }
      fs.writeFileSync(file, `${JSON.stringify(tools, null, 2)}\n`, "utf8");
      return;
    }
    // 文字列ではなく構造で比較する（キーの並び順は取得経路で変わる）
    expect(tools).toEqual(JSON.parse(fs.readFileSync(file, "utf8")));
  });
});
