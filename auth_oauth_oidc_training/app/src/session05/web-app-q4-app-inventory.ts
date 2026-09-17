// 練習問題 4 の解答。
// 実行: docker compose exec app npx tsx src/session05/web-app-q4-app-inventory.ts
// 書店を構成する 5 つのアプリについて、フローの判断表を Markdown の表として出力します。
import { chooseFlow, legacyChoice } from "./web-app-flow-chooser.js";
import type { Situation } from "./web-app-flow-chooser.js";

/** 棚卸しの対象。3 つの質問（利用者・ブラウザ・秘密）に答えるだけで埋まります */
export const INVENTORY: readonly Situation[] = [
  { label: "書店のフロント（ブラウザで動く web-app）", userPresent: true, hasBrowser: true, canKeepSecret: false },
  { label: "書店の管理画面（サーバー側で動く Web アプリ）", userPresent: true, hasBrowser: true, canKeepSecret: true },
  { label: "書店のスマートフォンアプリ（OS の外部ブラウザを開ける）", userPresent: true, hasBrowser: true, canKeepSecret: false },
  { label: "店頭のテレビ端末（文字入力が難しくブラウザを開けない）", userPresent: true, hasBrowser: false, canKeepSecret: true },
  { label: "夜間バッチ（batch-worker）", userPresent: false, hasBrowser: false, canKeepSecret: true },
];

const yesNo = (value: boolean, yes: string, no: string): string => (value ? yes : no);

console.log("| アプリ | 利用者 | ブラウザ | 秘密 | いま選ぶフロー | 2012 年ごろ |");
console.log("| :--- | :--- | :--- | :--- | :--- | :--- |");
for (const app of INVENTORY) {
  const past = legacyChoice(app);
  const row = [
    app.label,
    yesNo(app.userPresent, "いる", "いない"),
    yesNo(app.hasBrowser, "開ける", "開けない"),
    yesNo(app.canKeepSecret, "守れる", "守れない"),
    chooseFlow(app).flow,
    `${past.flow}${past.removed ? "（削除）" : ""}`,
  ];
  console.log(`| ${row.join(" | ")} |`);
}
