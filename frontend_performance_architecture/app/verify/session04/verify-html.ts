import { readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { build } from 'vite';

// app コンテナは NODE_ENV=development で動いている。build() の mode: 'production' だけでは
// React が開発版のままバンドルされる（初期 JS が約2倍になる）ため、環境変数も上書きする。
process.env.NODE_ENV = 'production';

/**
 * S04 のビルド成果物（HTML）を調べ、読み込みの指定が本文どおりになっていることを確かめる。
 * 実行: docker compose exec app node verify/session04/verify-html.ts
 * dist/ は preview が配信中なので、/tmp/ 配下に別に本番ビルドする。
 */
const ROOT = resolve(import.meta.dirname, '../..');
const OUT = '/tmp/s04-verify-dist';
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

const html = (page: string): string => readFileSync(join(OUT, 'pages', page, 'index.html'), 'utf8');
const count = (text: string, re: RegExp): number => text.match(re)?.length ?? 0;
const heroTag = (text: string): string => text.match(/<img\b[^>]*class="hero"[^>]*>/)?.[0] ?? '';

// 描画を止める外部 CSS（media 指定なしの stylesheet）
const STYLESHEET = /<link\b[^>]*\brel="stylesheet"[^>]*>/g;
// 属性のない <script> ＝ その場で同期実行されるインラインスクリプト
const SYNC_SCRIPT = /<script>/g;
const INLINE_STYLE = /<style\b/g;

const blocking = html('s04-blocking');
const noTag = html('s04-no-tag');
const optimized = html('s04-optimized');

check('s04-blocking: 外部 CSS の stylesheet が 1 本', count(blocking, STYLESHEET) === 1, `${count(blocking, STYLESHEET)} 本`);
check('s04-blocking: 同期スクリプトが 1 本', count(blocking, SYNC_SCRIPT) === 1, `${count(blocking, SYNC_SCRIPT)} 本`);
const badHero = heroTag(blocking);
check(
  's04-blocking: ヒーロー画像に width/height がなく loading="lazy"',
  !/\bwidth=/.test(badHero) && !/\bheight=/.test(badHero) && /loading="lazy"/.test(badHero),
);

check('s04-no-tag: 外部 CSS 1 本・同期スクリプト 0 本', count(noTag, STYLESHEET) === 1 && count(noTag, SYNC_SCRIPT) === 0);

check('s04-optimized: 外部 CSS の stylesheet が 0 本', count(optimized, STYLESHEET) === 0, `${count(optimized, STYLESHEET)} 本`);
check('s04-optimized: クリティカル CSS のインライン <style> が 1 つ', count(optimized, INLINE_STYLE) === 1, `${count(optimized, INLINE_STYLE)} つ`);
check('s04-optimized: 同期スクリプトが 0 本', count(optimized, SYNC_SCRIPT) === 0, `${count(optimized, SYNC_SCRIPT)} 本`);
const goodHero = heroTag(optimized);
check(
  's04-optimized: ヒーロー画像に width="720" height="240" fetchpriority="high"・lazy なし',
  /width="720"/.test(goodHero) && /height="240"/.test(goodHero) && /fetchpriority="high"/.test(goodHero) && !/loading="lazy"/.test(goodHero),
);

// 4,096 バイト未満の画像は Vite がデータ URL にしてしまう。別ファイルとして取得されていることを確かめる
const heroSrc = goodHero.match(/src="([^"]+)"/)?.[1] ?? '';
check('ヒーロー画像が別ファイルとして出力されている', /^\/assets\/[^/]+\.svg$/.test(heroSrc), heroSrc);

// Bad 版が待たされる CSS の大きさ（展開後のバイト数）
const cssHref = blocking.match(/<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)"/)?.[1] ?? '';
const cssBytes = cssHref ? statSync(join(OUT, cssHref)).size : 0;
check('描画を止める CSS が 25,000 バイト以上', cssBytes >= 25_000, `${cssBytes.toLocaleString('en-US')} バイト`);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS04 のビルド成果物の検証に成功しました。');
