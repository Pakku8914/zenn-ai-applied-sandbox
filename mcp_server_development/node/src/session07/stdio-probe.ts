/**
 * stdio トランスポートの罠を 5 つ再現する実験スクリプト
 *
 *   docker compose exec node npx tsx src/session07/stdio-probe.ts
 *
 * SDK のクライアントは使わず、生の JSON 文字列で通信します（電文レベルの観察のため）。
 * これはクライアント側のスクリプトなので console.log を使ってかまいません。
 */
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

/** 実験用の検索対象ディレクトリ。環境変数の継承を確認するために別の場所を使う */
const PROBE_ROOT = "/tmp/probe-docs";

const INITIALIZE = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: "2025-11-25",
    capabilities: {},
    clientInfo: { name: "stdio-probe", version: "1.0.0" },
  },
};

type InitializeResult = {
  result?: {
    protocolVersion?: string;
    serverInfo?: { name: string; version: string };
  };
};

function prepareDocs(): void {
  mkdirSync(PROBE_ROOT, { recursive: true });
  writeFileSync(`${PROBE_ROOT}/probe.md`, "# 実験用の文書\n\nVPN の設定について。\n", "utf8");
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 子プロセスを起こし、「標準出力から 1 行ずつ取り出す」機能を付けて返す。
 * 標準出力はチャンクで届くので、改行が現れるまで溜めてから 1 行として切り出す
 * ―― これが stdio の「行区切り」を自分で実装する部分です。
 */
function launch(script: string, env: NodeJS.ProcessEnv, inheritEnv = true) {
  const child = spawn("npx", ["tsx", script], {
    env: inheritEnv ? { ...process.env, ...env } : env,
  });

  const lines: string[] = [];
  const stderrLines: string[] = [];
  let buffer = "";
  let notify: (() => void) | undefined;

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    let index = buffer.indexOf("\n");
    while (index >= 0) {
      lines.push(buffer.slice(0, index));
      buffer = buffer.slice(index + 1);
      index = buffer.indexOf("\n");
    }
    notify?.();
  });

  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk: string) => {
    for (const line of chunk.split("\n")) {
      if (line.trim().length > 0) {
        stderrLines.push(line);
      }
    }
  });

  async function nextStdoutLine(timeoutMs: number): Promise<string | undefined> {
    const buffered = lines.shift();
    if (buffered !== undefined) {
      return buffered;
    }
    return await new Promise<string | undefined>((resolve) => {
      const timer = setTimeout(() => {
        notify = undefined;
        resolve(undefined);
      }, timeoutMs);
      notify = () => {
        const line = lines.shift();
        if (line === undefined) {
          return;
        }
        clearTimeout(timer);
        notify = undefined;
        resolve(line);
      };
    });
  }

  return { child, nextStdoutLine, stderrLines };
}

prepareDocs();

// ---------------------------------------------------------------- [1/5] 正常系
{
  const probe = launch("src/mid01/server.ts", { DOCSEARCH_ROOT: PROBE_ROOT });
  // 1 メッセージ = 1 行。末尾の改行がメッセージの終わりを表す
  probe.child.stdin.write(`${JSON.stringify(INITIALIZE)}\n`);
  const line = await probe.nextStdoutLine(20000);
  await delay(100); // 子の stderr が出そろうのを待つ
  const parsed = JSON.parse(line ?? "{}") as InitializeResult;
  console.log(
    `[1/5] 正常系: protocolVersion=${parsed.result?.protocolVersion}` +
      ` serverInfo=${parsed.result?.serverInfo?.name} v${parsed.result?.serverInfo?.version}` +
      ` / 子の stderr: ${probe.stderrLines[0] ?? "(なし)"}`,
  );
  probe.child.kill();
}

// ------------------------------------------------------------ [2/5] stdout 汚染
{
  const probe = launch("src/session07/bad-stdout-server.ts", { DOCSEARCH_ROOT: PROBE_ROOT });
  probe.child.stdin.write(`${JSON.stringify(INITIALIZE)}\n`);
  const line = await probe.nextStdoutLine(20000);
  try {
    JSON.parse(line ?? "");
    console.log("[2/5] stdout 汚染: 予期せず成功しました（console.log が消えていませんか？）");
  } catch {
    console.log(`[2/5] stdout 汚染: JSON.parse に失敗しました → 受け取った 1 行目: ${line}`);
  }
  probe.child.kill();
}

// -------------------------------------------------------------- [3/5] 行区切り
{
  const probe = launch("src/mid01/server.ts", { DOCSEARCH_ROOT: PROBE_ROOT });
  await delay(3000); // 起動を待つ（起動前に書くと取りこぼす）
  // ❌ 整形した JSON。改行を含むので 1 行 1 メッセージの規約に違反する
  probe.child.stdin.write(`${JSON.stringify(INITIALIZE, null, 2)}\n`);
  const line = await probe.nextStdoutLine(2000);
  console.log(
    line === undefined
      ? "[3/5] 行区切り: 2000ms 待っても応答がありませんでした（整形 JSON は 1 行 1 メッセージの規約に違反）"
      : `[3/5] 行区切り: 予期せず応答がありました → ${line}`,
  );
  probe.child.kill();
}

// -------------------------------------------------------------- [4/5] 環境変数
{
  // ❌ env を継承せず置き換えている。PATH が消えるので npx が見つからない
  const outcome = await new Promise<string>((resolve) => {
    const child = spawn("npx", ["tsx", "src/mid01/server.ts"], {
      env: { DOCSEARCH_ROOT: PROBE_ROOT },
    });
    child.on("error", (error: NodeJS.ErrnoException) => resolve(`code=${error.code ?? error.message}`));
    child.on("exit", (code) => resolve(`exit=${code ?? -1}`));
  });
  console.log(`[4/5] 環境変数: 起動に失敗しました → ${outcome}（env を置き換えると PATH が消える）`);
}

// ---------------------------------------------------------- [5/5] シャットダウン
{
  const probe = launch("src/mid01/server.ts", { DOCSEARCH_ROOT: PROBE_ROOT });
  probe.child.stdin.write(`${JSON.stringify(INITIALIZE)}\n`);
  await probe.nextStdoutLine(20000);
  const startedAt = Date.now();
  // 標準入力を閉じる = EOF。これが stdio サーバーの正常な終了指示
  probe.child.stdin.end();
  const exitCode = await new Promise<number | null>((resolve) => {
    probe.child.on("exit", (code) => resolve(code));
  });
  console.log(
    `[5/5] シャットダウン: stdin を閉じてから ${Date.now() - startedAt}ms で終了 / exitCode=${exitCode}`,
  );
}
