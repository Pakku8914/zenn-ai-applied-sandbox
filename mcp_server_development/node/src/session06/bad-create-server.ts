/**
 * ❌ 学習用の Bad 実装です。実務でまねしないでください。
 *
 * 意図的に入れてある欠陥
 *   ① テンプレート変数をそのままファイルパスに連結している（パストラバーサル）
 *   ② mimeType を指定していない
 *   ③ 補完を実装していない（クライアントは term に何を入れるか分からない）
 *   ④ 購読ケイパビリティを宣言していない
 *   ⑤ 例外をそのまま外に出すため、エラー文にサーバー内部のパスが載る
 *
 * なお正常系のファイル（src/session06/glossary/*.md）は用意していません。
 * このサーバーは「攻撃入力が通ってしまうこと」の確認だけに使います。
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";

const GLOSSARY_DIR = "src/session06/glossary";

export function createBadDashboardServer(): McpServer {
  const server = new McpServer({ name: "team-dashboard-bad", version: "0.3.0" });

  server.registerResource(
    "glossary_term",
    // ❌ 補完も一覧も無い
    new ResourceTemplate("glossary://{term}", { list: undefined }),
    // ❌ mimeType が無い
    { title: "社内用語辞書", description: "用語の定義を返します。" },
    async (uri, variables) => {
      const term = String(variables["term"] ?? "");
      // ❌ 検証なしでパスに連結。%2f をデコードするとスラッシュに戻る
      const filePath = path.join(GLOSSARY_DIR, decodeURIComponent(term));
      // ❌ 例外をそのまま外に出す（ENOENT のメッセージにサーバー内部のパスが載る）
      const text = readFileSync(filePath, "utf8");
      return { contents: [{ uri: uri.href, text }] };
    },
  );

  return server;
}
