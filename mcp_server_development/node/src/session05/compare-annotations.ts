/**
 * Good サーバーと Bad サーバーを「ホストの目線」で比較する
 *
 *   docker compose exec node npx tsx src/session05/compare-annotations.ts
 *
 * ホストは tools/list の注釈を見て、承認 UI を出すかどうかを決めます。
 * ここでは仕様の既定値に従った素朴なポリシーを実装して、
 * 注釈の書き方がユーザー体験と安全性をどう変えるかを確認します。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

type Annotations = {
  readOnlyHint?: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
  openWorldHint?: boolean;
};

/** 仕様の既定値：readOnlyHint は false、destructiveHint は true */
function decide(annotations: Annotations | undefined): string {
  const readOnly = annotations?.readOnlyHint ?? false;
  const destructive = annotations?.destructiveHint ?? true;
  if (readOnly) {
    return "自動実行してよい（読み取り専用）";
  }
  return destructive ? "ユーザー承認が必要（破壊的の可能性）" : "確認ダイアログ（書き込みだが非破壊）";
}

async function inspect(label: string, entry: string): Promise<void> {
  const transport = new StdioClientTransport({ command: "npx", args: ["tsx", entry] });
  const client = new Client({ name: "annotation-policy", version: "1.0.0" });
  await client.connect(transport);

  const { tools } = await client.listTools();
  console.log(`=== ${label}（${entry}）===`);
  for (const tool of [...tools].sort((a, b) => a.name.localeCompare(b.name))) {
    console.log(`${tool.name.padEnd(20)}: ${decide(tool.annotations)}`);
  }

  if (label.startsWith("Bad")) {
    // 追加確認：outputSchema 違反と isError の欠落
    const mismatched = await client
      .callTool({ name: "summarize_hours", arguments: { from: "2026-08-03", to: "2026-08-07" } })
      .then((result) => result as { isError?: boolean; [key: string]: unknown })
      .catch(() => ({ isError: true }));
    console.log(`outputSchema 不一致の呼び出しが失敗した=${mismatched.isError === true}`);

    const silent = (await client.callTool({
      name: "archive_project",
      arguments: { projectId: "p-nope" },
    })) as { isError?: boolean; content: Array<{ text?: string }> };
    console.log(
      `失敗を isError なしで返している=${silent.isError !== true} / 本文=${silent.content[0]?.text}`,
    );
  }

  await client.close();
}

await inspect("Good サーバー", "src/session05/server.ts");
await inspect("Bad サーバー", "src/session05/bad-server.ts");
console.log("判定: Bad では archive_project が確認なしで実行され、exportReportCSV には不要な確認が出ます");
