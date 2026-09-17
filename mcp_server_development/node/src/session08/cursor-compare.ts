/**
 * オフセット方式とキーセット方式の比較
 *
 * 1 ページ目を取得したあとにレコードが 1 件削除される、という現実的な状況で
 * 2 ページ目に何が起きるかを確認します。
 *
 * 実行： docker compose exec node npx tsx src/session08/cursor-compare.ts
 */
import {
  getObservations,
  paginateByKeyset,
  paginateByOffset,
  type Observation,
} from "./observations.js";

const LIMIT = 5;
const ids = (rows: readonly Observation[]): string => rows.map((r) => r.id).join(", ");

// 元データ（先頭 20 件だけを使って挙動を見ます）
const original = getObservations().slice(0, 20);

// --- オフセット方式 ---
const offsetPage1 = paginateByOffset(original, 0, LIMIT);
// 1 ページ目を返したあとで obs-000002 が削除された（観測ミスの取り消しなど）
const afterDelete = original.filter((row) => row.id !== "obs-000002");
const offsetPage2 = paginateByOffset(afterDelete, offsetPage1.nextOffset, LIMIT);
console.log(`[1/2] オフセット方式: 1ページ目=${ids(offsetPage1.items)}`);
console.log(`      削除後の2ページ目=${ids(offsetPage2.items)}`);

// --- キーセット方式 ---
const keysetPage1 = paginateByKeyset(original, undefined, LIMIT);
const keysetPage2 = paginateByKeyset(afterDelete, keysetPage1.lastId, LIMIT);
console.log(`[2/2] キーセット方式: 1ページ目=${ids(keysetPage1.items)}`);
console.log(`      削除後の2ページ目=${ids(keysetPage2.items)}`);
