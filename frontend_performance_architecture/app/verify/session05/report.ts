import { buildApp, bytesOf, entryOf, fmt, initialFiles, packageOf, displayId, sizeBy } from './bundle-stats.ts';

/**
 * S05：1ページ分の「初期 JS の中身」を表で出す。
 * 実行: docker compose exec app node verify/session05/report.ts [ページ名]
 *   ページ名は出発点なら main、改善版なら pages/ のディレクトリ名（例: s05-print-eager）
 */
const page = process.argv[2] ?? 'main';
const OUT = '/tmp/s05-report-dist';

const chunks = await buildApp(OUT);
const files = initialFiles(chunks, entryOf(chunks, page));

console.log(`ページ ${page} の初期 JS: ${files.length} ファイル / ${fmt(bytesOf(OUT, files))} バイト`);
for (const file of files.sort()) {
  console.log(`  ${file}  ${fmt(bytesOf(OUT, [file]))} バイト`);
}

const pct = (share: number): string => `${(share * 100).toFixed(1)}%`;

console.log('\nパッケージ別（renderedLength の合計）');
console.log('| パッケージ | renderedLength | 割合 |');
console.log('| :--- | ---: | ---: |');
for (const row of sizeBy(chunks, files, packageOf)) {
  console.log(`| ${row.label} | ${fmt(row.length)} | ${pct(row.share)} |`);
}

console.log('\nモジュール別（上位 8 件）');
console.log('| モジュール | renderedLength | 割合 |');
console.log('| :--- | ---: | ---: |');
for (const row of sizeBy(chunks, files, displayId).slice(0, 8)) {
  console.log(`| ${row.label} | ${fmt(row.length)} | ${pct(row.share)} |`);
}
