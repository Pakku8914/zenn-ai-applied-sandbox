/**
 * 契約テストの土台（テスト専用のヘルパー）
 *
 *   docker compose exec node npx vitest run src/session13
 *
 * ここに置くのは「テストの書き味を決める道具」だけです。
 * 期待値の判断はテストファイル側に書き、道具は判断をしません
 * （道具が判断を持つと、テストを読んでも何を保証しているのか分からなくなります）。
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { LATEST_PROTOCOL_VERSION, type JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";

/** ツール結果。SDK の型より緩く受け、テストで見たい部分だけを型にする */
export type ToolCallResult = {
  readonly content: readonly {
    readonly type: string;
    readonly text?: string;
    readonly uri?: string;
  }[];
  readonly structuredContent?: Record<string, unknown>;
  readonly isError?: boolean;
};

/** callTool に渡せるオプション（SDK の RequestOptions の一部だけを使う） */
export type CallOptions = {
  readonly timeout?: number;
  readonly signal?: AbortSignal;
  readonly resetTimeoutOnProgress?: boolean;
};

/**
 * サーバー定義とクライアントをメモリ上で直結する。
 * 両側の connect を Promise.all でまとめて待つのが要点で、片方だけ待つと
 * 相手が現れずにハングすることがあります。
 */
export async function connectInMemory(
  server: McpServer,
  clientName = "session13-test",
): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: clientName, version: "1.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

export async function callTool(
  client: Client,
  name: string,
  args: Record<string, unknown> = {},
  options?: CallOptions,
): Promise<ToolCallResult> {
  const result = await client.callTool({ name, arguments: args }, undefined, options);
  return result as unknown as ToolCallResult;
}

export function toolText(result: ToolCallResult): string {
  return result.content.map((block) => block.text ?? "").join("\n");
}

/**
 * 「ツール実行の失敗」を受け取る。
 * isError の確認をここに置くと、各テストは「文面の検査」だけに集中できます。
 */
export function expectToolFailure(result: ToolCallResult): string {
  if (result.isError !== true) {
    throw new Error(
      `失敗するはずの呼び出しが成功しました: ${JSON.stringify(result).slice(0, 200)}`,
    );
  }
  return toolText(result);
}

/** 非同期に起きることを待つ（キャンセルがサーバー側に届いたか等） */
export async function waitFor(condition: () => boolean, timeoutMs = 2000): Promise<void> {
  const startedAt = Date.now();
  while (!condition()) {
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error(`条件が ${timeoutMs}ms 以内に成立しませんでした`);
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

export type RawResponse = Record<string, unknown>;

/**
 * SDK の Client を通さず、生の JSON-RPC を往復させる。
 *
 * Client は「サーバーが宣言していない機能を呼ぼうとすると、送信前に自分で例外を投げる」
 * という親切な作りになっています。サーバーが返す本物のエラーコードを観測したいときは、
 * このガードを外して素の電文を流し込む必要があります（セッション2 と同じ発想です）。
 */
export async function rawSession(
  server: McpServer,
  options: { readonly protocolVersion?: string } = {},
): Promise<{
  readonly initializeResponse: RawResponse;
  request(method: string, params?: Record<string, unknown>): Promise<RawResponse>;
  close(): Promise<void>;
}> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);

  const waiters = new Map<number, (response: RawResponse) => void>();
  clientTransport.onmessage = (message: JSONRPCMessage) => {
    const record = message as unknown as RawResponse;
    const id = record["id"];
    if (typeof id === "number") {
      const waiter = waiters.get(id);
      waiters.delete(id);
      waiter?.(record);
    }
  };
  await clientTransport.start();

  let nextId = 1;
  async function request(method: string, params?: Record<string, unknown>): Promise<RawResponse> {
    const id = nextId++;
    const response = new Promise<RawResponse>((resolve) => waiters.set(id, resolve));
    const message = {
      jsonrpc: "2.0",
      id,
      method,
      ...(params === undefined ? {} : { params }),
    };
    await clientTransport.send(message as unknown as JSONRPCMessage);
    return response;
  }

  const initializeResponse = await request("initialize", {
    // 版はハードコードせず SDK の定数から取る（SDK 更新でテストが勝手に壊れないように）
    protocolVersion: options.protocolVersion ?? LATEST_PROTOCOL_VERSION,
    capabilities: {},
    clientInfo: { name: "session13-raw", version: "1.0.0" },
  });
  await clientTransport.send({
    jsonrpc: "2.0",
    method: "notifications/initialized",
  } as unknown as JSONRPCMessage);

  return {
    initializeResponse,
    request,
    async close() {
      await clientTransport.close();
    },
  };
}

/** レスポンスから result を取り出す（error だったら分かるように落とす） */
export function resultOf(response: RawResponse): Record<string, unknown> {
  const result = response["result"];
  if (typeof result !== "object" || result === null) {
    throw new Error(`result がありません: ${JSON.stringify(response).slice(0, 200)}`);
  }
  return result as Record<string, unknown>;
}
