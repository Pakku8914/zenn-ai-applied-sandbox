// フローを決める 3 つの質問は、セッション5 の chooseFlow() / legacyChoice() がすでに持っています。
// この章で新しく書くのは「第三者が運営するか」の 1 項目と、構成ごとの守りだけです。
import { chooseFlow, legacyChoice } from "../session05/web-app-flow-chooser.js";
import type { FlowId, LegacyChoice, Situation } from "../session05/web-app-flow-chooser.js";

/** セッション5 の判断材料に「第三者が運営するか」を 1 つ足すだけ */
export type Setup = Situation & {
  /** 資源を持つ側とは別の組織が運営するか */
  readonly thirdParty: boolean;
};

export type Decision = {
  readonly flow: FlowId;
  readonly reason: string;
  readonly legacy: LegacyChoice;
  readonly guards: readonly string[];
};

/** フローが決まったあとに付ける守り。フローと条件の両方から決まります */
export function guardsFor(s: Setup, flow: FlowId): string[] {
  const guards: string[] = [];
  if (flow === "authorization-code+pkce") {
    // ブラウザのリダイレクトを通るフローにだけ必要な 3 点
    guards.push("PKCE(S256)", "state の照合と使い捨て", "redirect_uri の完全一致");
    guards.push(s.canKeepSecret ? "トークンはサーバー側に保持" : "トークンの置き場所を見直す");
  }
  // 守れるのにクライアント認証をしない理由は無い
  if (flow !== "none" && s.canKeepSecret) guards.push("クライアント認証（client_secret）");
  // 貸す範囲はどの構成でも絞る。自社で運営しないクライアントは、登録できるスコープごと絞る
  if (flow !== "none") {
    guards.push(
      s.thirdParty ? "スコープを必要最小限にする（登録を許すスコープも絞る）" : "スコープを必要最小限にする",
    );
  }
  return guards;
}

export function decide(s: Setup): Decision {
  const { flow, reason } = chooseFlow(s);
  return { flow, reason, legacy: legacyChoice(s), guards: guardsFor(s, flow) };
}

export const SETUPS: readonly Setup[] = [
  { label: "店員の CLI ツール", userPresent: true, hasBrowser: true, canKeepSecret: false, thirdParty: false },
  { label: "レジの組み込み端末", userPresent: true, hasBrowser: false, canKeepSecret: true, thirdParty: false },
  { label: "夜間の在庫同期バッチ", userPresent: false, hasBrowser: false, canKeepSecret: true, thirdParty: false },
  { label: "売上ダッシュボード", userPresent: true, hasBrowser: true, canKeepSecret: false, thirdParty: false },
  { label: "読書記録アプリ ReadLog", userPresent: true, hasBrowser: true, canKeepSecret: true, thirdParty: true },
];
