import { measureMedian } from '../vitals-client.ts';
import { BAD, GOOD, conditionsLabel, createChecker, ms } from './helpers.ts';

/**
 * S16：アクセシビリティ対応（ライブリージョン・ロービングタブインデックス・フォーカスを残す仮想化）で
 * 入力応答が悪化していないことを、#keyword への「商品1」入力の INP 中央値で確かめる。
 * 時間の値は揺れるので、絶対値ではなく Bad 版との比（1.5 倍以下）で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session16/verify-inp.ts
 */
const { check, finish } = createChecker();
const input = { selector: '#keyword', value: '商品1' };

const bad = await measureMedian(BAD, { runs: 3, input });
const good = await measureMedian(GOOD, { runs: 3, input });

console.log(`条件: ${conditionsLabel()}（3 回の中央値）`);
console.log('| ページ | LCP | 入力 INP |');
console.log('| :--- | ---: | ---: |');
console.log(`| s16-catalog-bad | ${ms(bad.median.LCP)} | ${ms(bad.median.INP)} |`);
console.log(`| s16-catalog-good | ${ms(good.median.LCP)} | ${ms(good.median.INP)} |`);

const badInp = bad.median.INP;
const goodInp = good.median.INP;
check('両方のページで INP が計測できた', badInp !== undefined && goodInp !== undefined, `${ms(badInp)} / ${ms(goodInp)}`);
if (badInp !== undefined && goodInp !== undefined) {
  check('good の入力 INP が bad の 1.5 倍以下（対応で入力応答が悪化していない）', goodInp <= badInp * 1.5, `${ms(goodInp)} ≦ ${ms(badInp * 1.5)}`);
}

finish('S16 の入力応答');
