/**
 * SDK を使わない最小の MCP クライアント（TypeScript / 標準モジュールのみ）
 *
 * @modelcontextprotocol/sdk を一切 import せず、node:child_process だけで書きます。
 * id ごとに解決関数を Map に登録し、応答が届いた側から取り出して解決します。
 *
 * 実行： docker compose exec node npx tsx src/session02/exercises/mini-client.ts
 *
 * これはクライアント側のスクリプトなので console.log を使ってよい
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

interface JsonRpcMessage {
  jsonrpc: "2.0";
  id?: number;
  method?: string;
  params?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: { code: number; message: string };
}

// protocol-versions.ts で確認した値に合わせてください
const PROTOCOL_VERSION = "2025-11-25";
const DEFAULT_TIMEOUT_MS = 5000;

const child = spawn("npx", ["tsx", "src/server.ts"], {
  stdio: ["pipe", "pipe", "inherit"],
});
const childStdin = child.stdin;
const childStdout = child.stdout;
if (childStdin === null || childStdout === null) {
  throw new Error("子プロセスの標準入出力を確保できませんでした");
}

const pending = new Map<number, (message: JsonRpcMessage) => void>();
const stats = { requests: 0, responses: 0, errors: 0, notifications: 0, timeouts: 0 };

let buffer = "";
childStdout.on("data", (chunk: Buffer) => {
  buffer += chunk.toString("utf8");
  let index = buffer.indexOf("\n");
  while (index !== -1) {
    const line = buffer.slice(0, index).replace(/\r$/, "");
    buffer = buffer.slice(index + 1);
    if (line.length > 0) {
      console.log(`S->C ${line}`);
      const message = JSON.parse(line) as JsonRpcMessage;
      if (message.error !== undefined) stats.errors += 1;
      if (message.result !== undefined || message.error !== undefined) {
        stats.responses += 1;
      }
      if (message.id !== undefined) {
        const resolve = pending.get(message.id);
        if (resolve !== undefined) {
          pending.delete(message.id);
          resolve(message);
        }
      }
    }
    index = buffer.indexOf("\n");
  }
});

let nextId = 1;

function write(message: JsonRpcMessage): void {
  const line = JSON.stringify(message);
  console.log(`C->S ${line}`);
  childStdin.write(`${line}\n`);
}

/** 通知を送る。id を付けないので応答は待たない */
function notify(method: string, params?: Record<string, unknown>): void {
  const message: JsonRpcMessage = { jsonrpc: "2.0", method };
  if (params !== undefined) message.params = params;
  write(message);
  stats.notifications += 1;
}

/** リクエストを送り、同じ id の応答が返るまで待つ（タイムアウトで null） */
function request(
  method: string,
  params?: Record<string, unknown>,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<JsonRpcMessage | null> {
  const id = nextId;
  nextId += 1;
  stats.requests += 1;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      stats.timeouts += 1;
      resolve(null);
    }, timeoutMs);
    pending.set(id, (message) => {
      clearTimeout(timer);
      resolve(message);
    });
    const message: JsonRpcMessage = { jsonrpc: "2.0", id, method };
    if (params !== undefined) message.params = params;
    write(message);
  });
}

const init = await request("initialize", {
  protocolVersion: PROTOCOL_VERSION,
  capabilities: {},
  clientInfo: { name: "mini-client", version: "1.0.0" },
});
console.log(`    合意したバージョン: ${JSON.stringify(init?.result?.["protocolVersion"])}`);

notify("notifications/initialized");
console.log("    通知の応答を 1 秒だけ待ってみます（返らないことの確認）");
const before = stats.responses;
await sleep(1000);
stats.timeouts += 1;
if (stats.responses === before) {
  console.log("    → 1 秒待っても何も返りませんでした（通知には応答が無い）");
}

const tools = await request("tools/list", {});
console.log(`    ツール: ${JSON.stringify(tools?.result?.["tools"])}`);

const called = await request("tools/call", {
  name: "add",
  arguments: { a: 2, b: 3 },
});
console.log(`    result: ${JSON.stringify(called?.result)}`);

const failed = await request("tools/nonexistent", {});
console.log(`    error: ${JSON.stringify(failed?.error)}`);

childStdin.end();
await sleep(200);

console.log("\n--- 集計 ---");
console.log(`送ったリクエスト: ${stats.requests} 件`);
console.log(`返ってきた応答:   ${stats.responses} 件（うちエラー ${stats.errors} 件）`);
console.log(`送った通知:       ${stats.notifications} 件`);
console.log(`タイムアウト:     ${stats.timeouts} 回（通知の応答待ち）`);
