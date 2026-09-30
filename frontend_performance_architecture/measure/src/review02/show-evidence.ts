import { CONDITIONS } from '../vitals-client.ts';
import { KEYWORD, RUNS, evidenceRows, observeSubjects } from './evidence.ts';

/**
 * 横断復習② 問題5：4ページの証拠を表で出す。判定はしない（読者が表から判定する）。
 * 実行: docker compose exec measure node --experimental-strip-types src/review02/show-evidence.ts
 */
const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各${RUNS}回の中央値）`,
);
console.log(`入力: #keyword に「${KEYWORD}」（pressSequentially）`);
console.table(evidenceRows(await observeSubjects()));
