// 最終プロジェクト final01: 監査ログの出口。
// セッション 16 の 2 段構え（書いてよい項目だけを組み立てる → 出口で名前と値を確認する）を使い、
// RP 側で起きる出来事を足します。
import { redact } from "../session16/api-service-audit-log.js";

/** RP 側の出来事。リソースサーバー側の 4 つはセッション 16 の AuditEvent がそのまま使えます */
export type RpAuditEvent =
  | "login.succeeded"
  | "login.failed"
  | "login.policy_violation"
  | "refresh.rotated"
  | "refresh.reuse_detected"
  | "logout";

export type AuditSink = {
  /** 1 行 1 イベントの JSON。書き出す直前に redact() を通します */
  write(record: Readonly<Record<string, unknown>>): void;
  /** 書き出した行（検証と自己点検のため） */
  readonly lines: readonly string[];
};

/** out を渡さなければ何も表示しません。本番ではログ基盤への送信に差し替えます */
export function createAuditSink(out: (line: string) => void = (): void => undefined): AuditSink {
  const lines: string[] = [];
  return {
    write(record) {
      // 名前で落とす（access_token・cookie ほか）→ 残りを値の形で最終確認する
      const line = JSON.stringify(redact(record));
      lines.push(line);
      out(line);
    },
    get lines(): string[] {
      return lines;
    },
  };
}

/** 「正常に済んだ」出来事。これ以外は deny として記録し、あとから拾いやすくします */
const NORMAL_EVENTS: readonly RpAuditEvent[] = ["login.succeeded", "refresh.rotated", "logout"];

/** RP 側の記録を組み立てます。トークンを渡す引数がどこにも無いのが設計です */
export function rpAuditRecord(args: {
  readonly event: RpAuditEvent;
  readonly sub?: string;
  readonly clientId?: string;
  readonly reason: string;
  readonly now?: Date;
}): Record<string, unknown> {
  return {
    at: (args.now ?? new Date()).toISOString(),
    event: args.event,
    // 表示名ではなく、認可サーバーが決めた不変の識別子だけを残す
    sub: args.sub ?? "",
    clientId: args.clientId ?? "",
    decision: NORMAL_EVENTS.includes(args.event) ? "allow" : "deny",
    reason: args.reason,
  };
}
