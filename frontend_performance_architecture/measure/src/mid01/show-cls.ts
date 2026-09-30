import { pageUrl, shiftSources } from './lab.ts';

/**
 * 中間プロジェクト 問題3 の解答例：layout-shift エントリを、動いた要素と移動前後の y 座標つきで出す（判定はしない）。
 * 実行: docker compose exec measure node --experimental-strip-types src/mid01/show-cls.ts mid01-slow
 */
const name = process.argv[2] ?? 'mid01-slow';
const shifts = await shiftSources(pageUrl(name));

console.log(`対象: ${name}（バナーの表示を待ってから読んだ layout-shift）`);
if (shifts.length === 0) console.log('layout-shift は記録されませんでした');
for (const s of shifts) console.log(`value=${s.value}  ${s.sources.join(' / ')}`);
