// 問題 4 の解答: 利用者名で照合していた所有者チェックを、sub ベースへ移行します。
// 既存データには sub が入っていないので、「移行中だけ利用者名で代用する」段を作り、
// 代用したことを必ず記録に残します。
import type { Action, Order, Subject } from "../session02/api-authz-decide.js";
import type { TokenFacts } from "./api-authz-claims.js";
import { UNLINKED } from "./api-authz-directory.js";
import { authorize } from "./api-authz-policy.js";
import type { AuthzResult } from "./api-authz-policy.js";

/** lenient = 移行中（利用者名で代用する）、strict = sub が無ければ所有者と認めない */
export type MigrationMode = "lenient" | "strict";

type LegacyRow = {
  readonly orderId: string;
  /** 既存データには入っていない。初回ログインで埋まる */
  ownerSub: string;
  readonly ownerName: string;
  readonly storeId: string;
  readonly status: Order["status"];
};

const LEGACY_SEED: ReadonlyArray<LegacyRow> = [
  { orderId: "order-1001", ownerSub: "", ownerName: "alice", storeId: "shinjuku", status: "paid" },
  { orderId: "order-1002", ownerSub: "", ownerName: "alice", storeId: "shinjuku", status: "shipped" },
  { orderId: "order-1003", ownerSub: "", ownerName: "alice", storeId: "shinjuku", status: "canceled" },
  { orderId: "order-2001", ownerSub: "", ownerName: "bob", storeId: "shinjuku", status: "paid" },
  { orderId: "order-9001", ownerSub: "", ownerName: "alice", storeId: "ueno", status: "paid" },
];

export class MigratingDirectory {
  private readonly mode: MigrationMode;
  private readonly rows = new Map<string, LegacyRow>();
  private readonly profiles = new Map<string, Subject["attributes"]>();
  private readonly warned: string[] = [];

  constructor(mode: MigrationMode) {
    this.mode = mode;
    for (const row of LEGACY_SEED) this.rows.set(row.orderId, { ...row });
  }

  /** 初回ログインで sub が判明したら、その利用者の注文に書き込みます */
  linkAccount(sub: string, username: string, attributes: Subject["attributes"] = {}): number {
    this.profiles.set(sub, attributes);
    let linked = 0;
    for (const row of this.rows.values()) {
      if (row.ownerName === username) {
        row.ownerSub = sub;
        linked += 1;
      }
    }
    return linked;
  }

  attributesOf(sub: string): Subject["attributes"] {
    return this.profiles.get(sub) ?? {};
  }

  get warnings(): readonly string[] {
    return this.warned;
  }

  /**
   * 判定に渡す資源を作ります。所有者の決め方は 3 通りです。
   * 1. sub が入っている → それを使う（本来の姿）
   * 2. sub が無く strict → 誰の持ち物でもない扱いにする
   * 3. sub が無く lenient → 利用者名が一致すれば「この人の持ち物」とみなし、記録を残す
   */
  orderFor(orderId: string, facts: TokenFacts): Order | undefined {
    const row = this.rows.get(orderId);
    if (row === undefined) return undefined;

    if (row.ownerSub !== "") {
      return { orderId: row.orderId, ownerId: row.ownerSub, storeId: row.storeId, status: row.status };
    }
    if (this.mode === "strict") {
      return { orderId: row.orderId, ownerId: UNLINKED, storeId: row.storeId, status: row.status };
    }
    this.warned.push(`${row.orderId}: sub が未連携のため利用者名で照合しました（ownerName=${row.ownerName}）`);
    const ownerId = facts.username === row.ownerName ? facts.sub : UNLINKED;
    return { orderId: row.orderId, ownerId, storeId: row.storeId, status: row.status };
  }
}

/** 台帳から資源と属性を引いて判定します。戻り値は allow / deny:段 の文字列 */
export function judgeMigration(
  directory: MigratingDirectory,
  facts: TokenFacts,
  action: Action,
  orderId: string,
): string {
  const order = directory.orderFor(orderId, facts);
  if (order === undefined) return "not_found";
  const result: AuthzResult = authorize(facts, action, order, {
    attributes: directory.attributesOf(facts.sub),
  });
  return result.allow ? "allow" : `deny:${result.stage}`;
}
