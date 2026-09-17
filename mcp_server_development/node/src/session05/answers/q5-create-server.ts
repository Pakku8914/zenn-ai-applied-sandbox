/**
 * 問題5 の解答：Bad 実装を修正した版
 *
 * 修正後の姿は本文の create-server.ts と同一になります。
 * 「レビューの結論が既にある実装と一致する」ことは珍しくありません。
 * 大事なのは、なぜ一致するのかを説明できることです（上の欠陥表がその説明です）。
 *
 * Bad からの差分（すべて本文の実装で解消されている）
 *   ① archive_project の注釈を 4 つ明示（readOnlyHint: true の嘘を撤回）
 *   ② 失敗を isError: true で表明し、有効な ID を返す
 *   ③ reason を必須引数にして監査ログへ
 *   ④ exportReportCSV → export_report に改名し、読み取り専用の注釈を付ける
 *   ⑤ CSV 本文を resource_link に置き換える
 *   ⑥ summarize_hours の outputSchema と structuredContent を一致させる
 *   ⑦ すべての引数に形式・制約・description を付ける
 *   ⑧ すべてのツールに title と「いつ使うか」を含む description を付ける
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { createDashboardServer } from "../create-server.js";

export function createReviewedServer(): McpServer {
  return createDashboardServer();
}
