// 問題 6 の解答: 監査ログを「読める形」から「気づける形」に変えます。
// ログは溜めるだけでは監査になりません。何を異常とみなすかを決め、
// 見つけたら失効の指示に変えるところまでを 1 本にします。
import type { AuditEvent } from "./api-service-audit-log.js";
import { formatLine } from "./api-service-audit-log.js";
import { JtiDenyList } from "./api-service-revocation-policy.js";
import { findLeaks } from "./api-q3-log-redaction.js";

export type FindingKind = "repeated-denial" | "token-shared" | "privilege-jump" | "log-leak";

export type Finding = {
  readonly kind: FindingKind;
  /** 誰について気づいたか（分からないときは空） */
  readonly sub: string;
  /** どのトークンについて気づいたか（分からないときは空） */
  readonly jti: string;
  readonly detail: string;
};

export type AnalyzeOptions = {
  /** 同じ利用者の拒否が何回続いたら疑うか */
  readonly denialThreshold?: number;
};

/** 指示の対象。トークン 1 本を止めるか、その利用者のセッションを止めるか */
export type RevocationOrder = {
  readonly target: "token" | "session";
  readonly sub: string;
  readonly jti: string;
  readonly reason: FindingKind;
};

/**
 * イベント列を 1 度だけ走査して気づきを集めます。
 * 判定は「時刻順に並んでいる」ことを前提にします（並べ替えは呼ぶ側の責任です）。
 */
export function analyze(events: readonly AuditEvent[], options: AnalyzeOptions = {}): Finding[] {
  const threshold = options.denialThreshold ?? 3;
  /** sub → 連続した拒否の回数 */
  const denialsBySub = new Map<string, number>();
  /** jti → そのトークンが使われた接続元 */
  const ipsByJti = new Map<string, Set<string>>();
  /** 拒否されたことがあり、まだ許可されていない sub */
  const deniedSubs = new Set<string>();
  const findings: Finding[] = [];
  const note = (kind: FindingKind, event: AuditEvent, detail: string): void =>
    void findings.push({ kind, sub: event.sub, jti: event.jti, detail });

  for (const event of events) {
    // 1. ログ自体に秘密が混ざっていないか。混ざっていたら他の判定より先に言います
    const leaks = findLeaks(formatLine(event));
    if (leaks.length > 0) {
      note("log-leak", event, `記録に秘密が混ざっている（${leaks.map((leak) => leak.kind).join(",")}）`);
    }

    // 2. 同じトークンが複数の接続元から使われた（持ち出された疑い）
    if (event.jti !== "" && event.ip !== "") {
      const ips = ipsByJti.get(event.jti) ?? new Set<string>();
      ips.add(event.ip);
      ipsByJti.set(event.jti, ips);
      // 2 つ目が現れた回だけ気づきます（3 つ目・4 つ目で繰り返し出さない）
      if (ips.size === 2) note("token-shared", event, `同じ jti が ${[...ips].join(" と ")} から使われた`);
    }

    if (event.decision === "deny") {
      // 3. 拒否が続く（権限の壁を探している疑い）
      const count = (denialsBySub.get(event.sub) ?? 0) + 1;
      denialsBySub.set(event.sub, count);
      deniedSubs.add(event.sub);
      // しきい値に「達した回」だけ出します（>= にすると 4 回目以降も出続けます）
      if (count === threshold) note("repeated-denial", event, `拒否が ${threshold} 回続いた`);
      continue;
    }

    // 4. 拒否され続けていた利用者が、急に通るようになった（権限が増えた）
    if (deniedSubs.has(event.sub)) {
      note("privilege-jump", event, "拒否のあとに同じ操作が通った。権限の変更を確認する");
      deniedSubs.delete(event.sub);
    }
  }
  return findings;
}

/**
 * 気づきを失効の指示に変えます。
 * 盗まれた疑いはトークン 1 本、権限を探られた疑いはセッションごと止めます。
 */
export function toOrders(findings: readonly Finding[]): RevocationOrder[] {
  const orders: RevocationOrder[] = [];
  for (const finding of findings) {
    if (finding.kind === "token-shared" && finding.jti !== "") {
      orders.push({ target: "token", sub: finding.sub, jti: finding.jti, reason: finding.kind });
    }
    if (finding.kind === "repeated-denial" && finding.sub !== "") {
      orders.push({ target: "session", sub: finding.sub, jti: "", reason: finding.kind });
    }
  }
  return orders;
}

/**
 * トークン 1 本を止める指示だけを、手元のブロックリストに反映します。
 * セッションの停止はリソースサーバーでは実行できません（認可サーバーに頼む仕事です）。
 */
export function applyOrders(deny: JtiDenyList, orders: readonly RevocationOrder[], expiresAt: number): number {
  const tokenOrders = orders.filter((order) => order.target === "token");
  for (const order of tokenOrders) deny.revoke(order.jti, expiresAt);
  return tokenOrders.length;
}

/** 気づきを 1 行ずつ人が読む形にします */
export function findingReport(findings: readonly Finding[]): string[] {
  return findings.map((finding) => `${finding.kind}: ${finding.detail}`);
}
