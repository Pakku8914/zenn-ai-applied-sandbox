// 問題 1 の解答: 秘密鍵の保管場所を比べ、要件から 1 つ選びます。
// 「どれが安全か」ではなく「何を諦めるか」を並べるのが比較表の役目です。

export type KeyStorage = "source-code" | "env-var" | "secret-manager" | "hsm";

export type StorageFacts = {
  readonly storage: KeyStorage;
  /** 秘密を読める範囲 */
  readonly readableBy: string;
  /** 鍵が保管場所の外へ出るか（出ないなら、盗んでも使えない） */
  readonly keyLeavesBoundary: boolean;
  /** 誰がいつ読んだかの記録が残るか */
  readonly hasAccessLog: boolean;
  /** 差し替えに何が必要か */
  readonly rotationCost: string;
};

const facts = (
  readableBy: string,
  keyLeavesBoundary: boolean,
  hasAccessLog: boolean,
  rotationCost: string,
): Omit<StorageFacts, "storage"> => ({ readableBy, keyLeavesBoundary, hasAccessLog, rotationCost });

export const STORAGES: Readonly<Record<KeyStorage, StorageFacts>> = {
  "source-code": {
    storage: "source-code",
    // 消しても履歴から読める。ここがこの保管場所の致命的な点です
    ...facts("リポジトリを読める全員（履歴に残るので消しても読める）", true, false, "修正とデプロイ。履歴からは消えない"),
  },
  "env-var": {
    storage: "env-var",
    ...facts("そのプロセスと、同じホストで実行できる人", true, false, "設定変更と再起動"),
  },
  "secret-manager": {
    storage: "secret-manager",
    ...facts("権限を与えたアプリと運用者", true, true, "保管側で新しい値を登録するだけ"),
  },
  hsm: {
    storage: "hsm",
    // 鍵を渡さず、署名の結果だけを返す。だから盗めません
    ...facts("誰も読めない（署名を頼むことしかできない）", false, true, "機器の操作が必要。手順が重い"),
  },
};

export type StorageProblem = "in-version-control" | "no-access-log" | "key-is-exportable";

/** 保管場所 1 つを査読します。指摘の順序は固定です */
export function reviewStorage(storage: KeyStorage): StorageProblem[] {
  const target = STORAGES[storage];
  const problems: StorageProblem[] = [];
  if (storage === "source-code") problems.push("in-version-control");
  if (!target.hasAccessLog) problems.push("no-access-log");
  if (target.keyLeavesBoundary) problems.push("key-is-exportable");
  return problems;
}

export type StorageRequirement = {
  /** 鍵を読んだ記録が要るか（監査の要件） */
  readonly needsAccessLog: boolean;
  /** 鍵そのものを外に出してはいけないか */
  readonly mustNotExportKey: boolean;
  /** 外部の保管サービスを使えるか（閉じた環境では使えないことがあります） */
  readonly canUseManagedService: boolean;
};

export type StorageChoice = {
  readonly storage: KeyStorage | "unsatisfiable";
  readonly reason: string;
};

/**
 * 要件から保管場所を選びます。判定の順序が設計判断です。
 * source-code は要件に関わらず選びません（候補に入れてはいけません）。
 */
export function chooseStorage(req: StorageRequirement): StorageChoice {
  if (req.mustNotExportKey) {
    return { storage: "hsm", reason: "鍵を外に出さない要件は、署名を機器に頼む形でしか満たせない" };
  }
  if (req.needsAccessLog) {
    return req.canUseManagedService
      ? { storage: "secret-manager", reason: "読んだ記録が要るなら、記録を残す保管場所に置く" }
      : { storage: "unsatisfiable", reason: "記録が要るのに保管サービスが使えない。自前の保管と記録を用意する" };
  }
  return { storage: "env-var", reason: "記録も持ち出し防止も要らないなら、環境変数で足りる" };
}
