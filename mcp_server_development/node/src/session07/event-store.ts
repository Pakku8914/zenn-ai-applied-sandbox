/**
 * インメモリの EventStore（再開可能性のための保存庫）
 *
 * SDK は EventStore の「型」だけを定義し、実装を提供していません。
 * 本番はプロセスをまたぐので Redis などに置く必要があり、SDK が決め打ちできないためです。
 *
 * 正確な型は次のコマンドで確認できます。
 *   docker compose exec node sh -c 'cat node_modules/@modelcontextprotocol/sdk/dist/esm/server/streamableHttp.d.ts'
 */
import type { EventStore } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";

/**
 * イベント ID の区切り文字。
 * SDK がサーバー起点ストリームに使う ID は "_GET_stream" のように "_" を含むので、
 * "_" を区切りにすると分解できなくなる。
 */
const SEPARATOR = "#";

type StoredEvent = {
  readonly streamId: string;
  readonly message: JSONRPCMessage;
};

export class InMemoryEventStore implements EventStore {
  private readonly events = new Map<string, StoredEvent>();
  /** 保存順。再送は「この順序で lastEventId より後ろ」を送る */
  private readonly order: string[] = [];
  private counter = 0;

  /** 上限を必ず設ける。無制限だとメモリ枯渇と情報の滞留が起きる */
  constructor(private readonly maxEvents = 1000) {}

  async storeEvent(streamId: string, message: JSONRPCMessage): Promise<string> {
    this.counter += 1;
    const eventId = `${streamId}${SEPARATOR}${String(this.counter).padStart(6, "0")}`;
    this.events.set(eventId, { streamId, message });
    this.order.push(eventId);
    while (this.order.length > this.maxEvents) {
      const oldest = this.order.shift();
      if (oldest !== undefined) {
        this.events.delete(oldest);
      }
    }
    return eventId;
  }

  async replayEventsAfter(
    lastEventId: string,
    { send }: { send: (eventId: string, message: JSONRPCMessage) => Promise<void> },
  ): Promise<string> {
    // ストリーム ID は ①保存済みイベントから ②ID の形式から の順で復元する
    const streamId = this.events.get(lastEventId)?.streamId ?? streamIdOf(lastEventId);
    if (streamId === undefined) {
      // 形式すら合わない ID は無視する（偽の Last-Event-ID を投げられても壊れないように）
      return "";
    }

    const anchor = this.order.indexOf(lastEventId);
    // 未知の ID（上限で捨てた・偽物）は「再送なし」にする。
    // 全件送り直すと、切断のたびに履歴が丸ごと再送されて通信量が爆発する
    const from = anchor === -1 ? this.order.length : anchor + 1;

    for (const eventId of this.order.slice(from)) {
      const stored = this.events.get(eventId);
      if (stored === undefined || stored.streamId !== streamId) {
        continue;
      }
      await send(eventId, stored.message);
    }
    return streamId;
  }

  /** 実験・監視用 */
  size(): number {
    return this.order.length;
  }
}

function streamIdOf(eventId: string): string | undefined {
  const at = eventId.lastIndexOf(SEPARATOR);
  return at <= 0 ? undefined : eventId.slice(0, at);
}
