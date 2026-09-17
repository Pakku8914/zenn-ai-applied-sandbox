// セッション 2: 認可の判断を 1 つの関数にまとめた例。
// このファイルは計算だけを行い、画面への出力はしません（テストしやすくするため）。

/** 判断の主体。認証が終わって「誰であるか」が確定した状態を表します。 */
export type Subject = {
  /** 本人：認証で確定した利用者の識別子 */
  readonly userId: string;
  /** 役割：その利用者に与えられた立場（例: customer, staff） */
  readonly roles: readonly string[];
  /** 属性：いまの状態。担当店舗はどこか、利用停止中かどうか */
  readonly attributes: {
    readonly storeId?: string;
    readonly suspended?: boolean;
  };
};

/** 資源：判断の対象になる注文。資源そのものの性質も判断材料になります。 */
export type Order = {
  readonly orderId: string;
  readonly ownerId: string;
  readonly storeId: string;
  readonly status: "paid" | "shipped" | "canceled";
};

/** 操作：資源に対して行いたいこと。 */
export type Action = "read" | "cancel" | "refund";

/** 判断の結果。許可・不許可と、そう判断した理由をセットで返します。 */
export type Decision = {
  readonly allow: boolean;
  readonly reason: string;
};

/**
 * 「この主体に、この資源へのこの操作を許すか」を判断します。
 * 認証（誰であるか）は終わっている前提で、認可（何を許すか）だけを決めます。
 */
export function decide(subject: Subject, action: Action, order: Order): Decision {
  // 属性：利用停止中なら、役割や所有者に関係なく拒否する（拒否は最初に落とす）
  if (subject.attributes.suspended === true) {
    return { allow: false, reason: "利用停止中の利用者です" };
  }

  // 判断材料を 3 つの真偽値に落とす
  const isOwner = subject.userId === order.ownerId; // 本人 × 資源
  const isStaff = subject.roles.includes("staff"); // 役割
  const isSameStore = subject.attributes.storeId === order.storeId; // 属性 × 資源

  if (action === "read") {
    if (isOwner) {
      return { allow: true, reason: "自分の注文なので読めます" };
    }
    if (isStaff && isSameStore) {
      return { allow: true, reason: "担当店舗の注文なので staff として読めます" };
    }
    return { allow: false, reason: "自分の注文でも担当店舗の注文でもありません" };
  }

  if (action === "cancel") {
    // 資源：資源の状態によって、誰であっても許されない操作がある
    if (order.status === "shipped") {
      return { allow: false, reason: "発送済みの注文は取り消せません" };
    }
    if (order.status === "canceled") {
      return { allow: false, reason: "すでに取り消された注文です" };
    }
    if (isOwner) {
      return { allow: true, reason: "自分の支払い済みの注文なので取り消せます" };
    }
    if (isStaff && isSameStore) {
      return { allow: true, reason: "担当店舗の注文なので staff として取り消せます" };
    }
    return { allow: false, reason: "他人の注文は取り消せません" };
  }

  // action === "refund"
  if (!isStaff) {
    return { allow: false, reason: "返金は staff の権限です" };
  }
  if (!isSameStore) {
    return { allow: false, reason: "担当外の店舗の注文は返金できません" };
  }
  if (order.status !== "canceled") {
    return { allow: false, reason: "取り消されていない注文は返金できません" };
  }
  return { allow: true, reason: "担当店舗の取り消し済みの注文なので返金できます" };
}
