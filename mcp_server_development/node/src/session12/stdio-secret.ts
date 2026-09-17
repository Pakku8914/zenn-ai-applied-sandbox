/**
 * stdio サーバーにおけるシークレットの受け取り方
 *
 * 起動（ホストの設定ファイルからは env で渡される）:
 *   docker compose exec -e DOCSEARCH_API_KEY=demo-key-0123456789 node \
 *     npx tsx src/session12/stdio-secret.ts
 * 未設定で起動すると、起動時に落ちることを確認できます:
 *   docker compose exec node npx tsx src/session12/stdio-secret.ts
 */
import { createHash } from "node:crypto";

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { resolveDocsRoot } from "../mid01/config.js";
import { createDocSearchServer } from "../mid01/create-server.js";

// ① コードに書かない。引数でも渡さない（引数はプロセス一覧から見える）
const apiKey = process.env["DOCSEARCH_API_KEY"];

// ② 無ければ起動時に失敗させる。「無いまま動いて後で謎の失敗」より早く落ちるほうがよい
if (apiKey === undefined || apiKey.trim() === "") {
  console.error(
    "[docsearch] 環境変数 DOCSEARCH_API_KEY が設定されていません。ホストの設定（env）で渡してください。",
  );
  process.exit(1);
}

// ③ 値そのものはログに出さない。相関できる指紋だけを出す
const fingerprint = createHash("sha256").update(apiKey, "utf8").digest("hex").slice(0, 8);
console.error(`[docsearch] 下流 API の資格情報を受け取りました（fingerprint=${fingerprint}）`);

const server = createDocSearchServer({ docsRoot: resolveDocsRoot([]) });
await server.connect(new StdioServerTransport());
// ④ このサーバーは「利用者を認証していない」ことを明示しておく
console.error("[docsearch] stdio で待機しています（利用者の認証は行っていません）");
