/**
 * TypeScript SDK が持っているプロトコルバージョン定数を読み出す
 *
 * MCP は仕様改訂が速いため、「本に書いてあるバージョン」ではなく
 * 「いま手元の SDK が対応しているバージョン」を確認する習慣をつけます。
 *
 * 実行： docker compose exec node npx tsx src/session02/protocol-versions.ts
 */
import {
  LATEST_PROTOCOL_VERSION,
  SUPPORTED_PROTOCOL_VERSIONS,
} from "@modelcontextprotocol/sdk/types.js";

console.log(`LATEST_PROTOCOL_VERSION = ${LATEST_PROTOCOL_VERSION}`);
console.log("SUPPORTED_PROTOCOL_VERSIONS:");
for (const version of SUPPORTED_PROTOCOL_VERSIONS) {
  const mark = version === LATEST_PROTOCOL_VERSION ? "  ← 既定で提示される版" : "";
  console.log(`  - ${version}${mark}`);
}
