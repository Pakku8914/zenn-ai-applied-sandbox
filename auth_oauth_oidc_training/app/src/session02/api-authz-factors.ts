// セッション 2 練習問題 5 の解答: 成立している判断材料だけを並べて返します。
// 判断そのもの（許可・不許可）はここでは決めません。「材料の棚卸し」だけを行います。
import type { Order, Subject } from "./api-authz-decide.js";

/** 認可の判断材料の 4 分類。 */
export type Factor = "本人" | "役割" | "属性" | "資源";

/**
 * subject と order を見比べて、成立している材料を返します。
 * 並び順は常に 本人 → 役割 → 属性 → 資源 に固定します（結果を比較しやすくするため）。
 */
export function matchedFactors(subject: Subject, order: Order): Factor[] {
  const factors: Factor[] = [];
  if (subject.userId === order.ownerId) {
    factors.push("本人"); // 注文の持ち主である
  }
  if (subject.roles.includes("staff")) {
    factors.push("役割"); // staff の立場を持っている
  }
  if (subject.attributes.storeId === order.storeId) {
    factors.push("属性"); // 担当店舗が注文の店舗と一致する
  }
  if (order.status === "paid") {
    factors.push("資源"); // 注文がまだ手を加えられる状態にある
  }
  return factors;
}
