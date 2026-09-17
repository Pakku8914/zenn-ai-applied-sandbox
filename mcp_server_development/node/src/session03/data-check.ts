/**
 * データ層だけの動作確認（MCP を経由しない）
 *
 * サーバーを起動せずにロジックを確かめられるのが、データ層を分離した最初の恩恵です。
 * このスクリプトはクライアント側と同じ「ただのプログラム」なので console.log を使ってかまいません。
 */
import { listMembers, summarizeHours } from "./data.js";

console.log("platform チーム:", listMembers("platform").map((member) => member.id).join(", "));

const week = summarizeHours({ from: "2026-08-03", to: "2026-08-07" });
console.log("合計時間:", week.totalHours);
console.log("対象人数:", week.members.length);
console.log("m-002 の内訳:", summarizeHours({ from: "2026-08-03", to: "2026-08-07", memberId: "m-002" }).totalHours);
