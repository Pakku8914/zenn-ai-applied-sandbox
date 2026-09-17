// 練習問題 3 の解答。
// 実行: docker compose exec app npx tsx src/session05/web-app-q3-flow-report.ts
// 4 つの状況について「いま選ぶフロー」と「2012 年ごろの選択」を並べて表示します。
import { SITUATIONS, chooseFlow, legacyChoice } from "./web-app-flow-chooser.js";

console.log("=== 用途からフローを選ぶ ===");
for (const situation of SITUATIONS) {
  const now = chooseFlow(situation);
  const past = legacyChoice(situation);
  console.log(situation.label);
  console.log(`  いま選ぶフロー: ${now.flow}`);
  console.log(`  理由: ${now.reason}`);
  console.log(`  2012 年ごろの選択: ${past.flow}（${past.removed ? "2.1 で削除" : "現役"}）`);
}
