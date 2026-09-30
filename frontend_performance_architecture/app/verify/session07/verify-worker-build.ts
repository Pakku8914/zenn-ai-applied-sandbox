import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { build } from 'vite';

// app コンテナは NODE_ENV=development で動いている。build() の mode: 'production' だけでは
// React が開発版のままバンドルされる（初期 JS が約2倍になる）ため、環境変数も上書きする。
process.env.NODE_ENV = 'production';

/**
 * S07 のビルド成果物を調べ、Worker が別ファイルとして出力されていることを確かめる。
 * 実行: docker compose exec app node verify/session07/verify-worker-build.ts
 * dist/ は preview が配信中なので、/tmp/ 配下に別に本番ビルドする。
 */
const ROOT = resolve(import.meta.dirname, '../..');
const OUT = '/tmp/s07-verify-dist';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

await build({
  root: ROOT,
  mode: 'production',
  logLevel: 'silent',
  build: { outDir: OUT, emptyOutDir: true },
});

for (const page of ['s07-baseline', 's07-chunked', 's07-worker']) {
  check(`${page} のページが出力されている`, existsSync(join(OUT, 'pages', page, 'index.html')));
}

const assets = readdirSync(join(OUT, 'assets'));
const workerFiles = assets.filter((f) => /^points\.worker-[\w-]+\.js$/.test(f));
check('Worker が別の JS ファイル（points.worker-*.js）として 1 本出力されている', workerFiles.length === 1, workerFiles.join(', ') || 'なし');

// Worker の中身に重い計算（内側ループ 200,000 回）が入っていること。圧縮で 2e5 と書かれることもある
const workerCode = workerFiles[0] ? readFileSync(join(OUT, 'assets', workerFiles[0]), 'utf8') : '';
check('Worker のファイルに重い計算が含まれている', /2e5|200000/.test(workerCode));

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS07 のビルド成果物の検証に成功しました。');
