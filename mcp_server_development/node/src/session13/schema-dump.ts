/**
 * tools/list を人が読める形で書き出す
 *
 *   docker compose exec node npx tsx src/session13/schema-dump.ts
 *   docker compose exec node npx tsx src/session13/schema-dump.ts --write
 *
 * --write を付けるとベースラインを上書きします（スキーマを意図的に変えたときに使う）。
 * クライアント側のスクリプトなので stdout に書いてかまいません
 * （サーバープロセスでは stdout が JSON-RPC の通信路になるので禁止です）。
 */
import fs from "node:fs";
import path from "node:path";

import { createDocSearchServer } from "../mid01/create-server.js";
import { createFixtureServer } from "./fixture-server.js";
import { connectInMemory } from "./harness.js";

const SNAPSHOT_DIR = path.resolve("src/session13/__snapshots__");
const shouldWrite = process.argv.includes("--write");

const targets = [
  { name: "mid01-tools-list", server: () => createDocSearchServer({ docsRoot: path.resolve("src/mid01/docs") }) },
  { name: "fixture-tools-list", server: () => createFixtureServer() },
];

fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });

for (const target of targets) {
  const client = await connectInMemory(target.server(), "schema-dump");
  const { tools } = await client.listTools();
  await client.close();

  const serialized = `${JSON.stringify(tools, null, 2)}\n`;
  console.log(`===== ${target.name} =====`);
  console.log(serialized);

  if (shouldWrite) {
    const file = path.join(SNAPSHOT_DIR, `${target.name}.json`);
    fs.writeFileSync(file, serialized, "utf8");
    console.log(`書き出しました: ${file}`);
  }
}
