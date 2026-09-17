/**
 * 問題2 の解答：3 つの欠陥を修正した stdio エントリーポイント
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// 欠陥①の修正: ESM では相対 import に .js 拡張子が必要
import { createDashboardServer } from "../create-server.js";

const server = createDashboardServer();
const transport = new StdioServerTransport();

// 欠陥③の修正: トランスポートに接続していなかった
await server.connect(transport);

// 欠陥②の修正: サーバープロセスの stdout は JSON-RPC の通信路。ログは stderr へ
console.error("[q2-server] stdio でリクエストを待機しています");
