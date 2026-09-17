/**
 * stdio 中継スクリプト（電文キャプチャ用プロキシ）
 *
 * クライアントからは「これがサーバー」に見えます。本物のサーバーは子プロセスとして
 * 起動し、流れてきたバイト列をそのまま素通しさせながら、1 行ずつログファイルへ記録します。
 *
 * 注意：このスクリプト自身の標準出力はクライアントへの通信路です。
 * ログを console.log で出すことは絶対にできません（記録先はファイルと stderr だけ）。
 */
import { spawn } from "node:child_process";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

// 記録先。node/ はホストにバインドマウントされているのでエディタからも開けます
const LOG_PATH = "captures/stdio.log";

mkdirSync(dirname(LOG_PATH), { recursive: true });
// 実行のたびに空にする（前回のキャプチャと混ざらないようにするため）
writeFileSync(LOG_PATH, "");

// 本物のサーバーを子プロセスとして起動する。
// stderr を "inherit"（このプロセスの stderr にそのまま流す）にしておくと、
// サーバーが出したログがターミナルにそのまま見えます
const child = spawn("npx", ["tsx", "src/server.ts"], {
  stdio: ["pipe", "pipe", "inherit"],
});

const childStdin = child.stdin;
const childStdout = child.stdout;
if (childStdin === null || childStdout === null) {
  throw new Error("子プロセスの標準入出力を確保できませんでした");
}

/** 受け取ったチャンクを改行で区切り、1 行そろうたびにコールバックへ渡す */
function createLineReader(onLine: (line: string) => void): (chunk: Buffer) => void {
  let buffer = "";
  return (chunk: Buffer) => {
    buffer += chunk.toString("utf8");
    let index = buffer.indexOf("\n");
    while (index !== -1) {
      const line = buffer.slice(0, index).replace(/\r$/, "");
      buffer = buffer.slice(index + 1);
      if (line.length > 0) {
        onLine(line);
      }
      index = buffer.indexOf("\n");
    }
  };
}

/** 方向タグ（4 文字）を付けて 1 行記録する。同期書き込みなので取りこぼしません */
function record(direction: "C->S" | "S->C", line: string): void {
  appendFileSync(LOG_PATH, `${direction} ${line}\n`);
}

const readFromClient = createLineReader((line) => record("C->S", line));
const readFromServer = createLineReader((line) => record("S->C", line));

// クライアント → サーバー：記録してから素通しする
process.stdin.on("data", (chunk: Buffer) => {
  readFromClient(chunk);
  childStdin.write(chunk);
});
process.stdin.on("end", () => {
  childStdin.end();
});

// サーバー → クライアント：記録してから素通しする
childStdout.on("data", (chunk: Buffer) => {
  readFromServer(chunk);
  process.stdout.write(chunk);
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});

// クライアントが接続を切ったら子プロセスも道連れにする（プロセスの取り残しを防ぐ）
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    child.kill(signal);
    process.exit(0);
  });
}
