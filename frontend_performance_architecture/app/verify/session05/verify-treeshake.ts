import { resolve } from 'node:path';
import { build } from 'vite';
import { ROOT } from './bundle-stats.ts';

// app コンテナは NODE_ENV=development で動いている。build() の mode: 'production' だけでは
// React が開発版のままバンドルされる（初期 JS が約2倍になる）ため、環境変数も上書きする。
process.env.NODE_ENV = 'production';

/**
 * S05：Tree Shaking が効く条件・効かない条件を、小さな入口を本番ビルドして確かめる。
 * 実行: docker compose exec app node verify/session05/verify-treeshake.ts
 * 使われない関数に入れておいた目印の文字列が、出力に残るかどうかで判定する（決定的）。
 */
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

/** src/sessions/s05/treeshake/<entry>.ts だけを入口にして本番ビルドし、出力コードを1つの文字列で返す */
async function bundle(entry: string, declareLibSideEffectFree = false): Promise<string> {
  const result = await build({
    root: ROOT,
    // 検証したい入口だけを入れるため、プロジェクトの vite.config.ts（全ページが入口）は読まない
    configFile: false,
    mode: 'production',
    logLevel: 'silent',
    build: {
      outDir: `/tmp/s05-treeshake-${entry}`,
      emptyOutDir: true,
      write: false,
      rollupOptions: {
        input: resolve(ROOT, `src/sessions/s05/treeshake/${entry}.ts`),
        // package.json の "sideEffects": false と同じ宣言を、ビルド設定の側から lib/ に対して行う
        treeshake: declareLibSideEffectFree
          ? { moduleSideEffects: (id: string) => !id.includes('/treeshake/lib/') }
          : undefined,
      },
    },
  });
  const outputs = Array.isArray(result) ? result : [result];
  return outputs
    .flatMap((out) => out.output)
    .map((item) => (item.type === 'chunk' ? item.code : ''))
    .join('\n');
}

const size = (code: string): string => `${Buffer.byteLength(code).toLocaleString('en-US')} バイト`;

const named = await bundle('entry-named');
check('名前付き import: 使う formatPrice は残る', named.includes('ja-JP'), size(named));
check('名前付き import: 使わない formatDate は消える', !named.includes('[format-date]'));

const namespace = await bundle('entry-namespace');
check('名前空間＋実行時のキー: formatDate まで残る', namespace.includes('[format-date]'), size(namespace));

const nsStatic = await bundle('entry-namespace-static');
check('練習問題2 (B) 名前空間＋固定の名前: formatDate は消える', nsStatic.includes('ja-JP') && !nsStatic.includes('[format-date]'), size(nsStatic));

const nsEscape = await bundle('entry-namespace-escape');
check('練習問題2 (C) 名前空間を関数に渡す: formatDate まで残る', nsEscape.includes('[format-date]'), size(nsEscape));

const barrel = await bundle('entry-barrel');
check('バレル経由（宣言なし）: 触れていない analytics の副作用が残る', barrel.includes('[analytics] ready'), size(barrel));

const declared = await bundle('entry-barrel', true);
check('バレル経由（副作用なしを宣言）: analytics が消える', !declared.includes('[analytics] ready'), size(declared));
check('バレル経由（副作用なしを宣言）: formatPrice は残る', declared.includes('ja-JP'));

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS05 の Tree Shaking の検証に成功しました。');
