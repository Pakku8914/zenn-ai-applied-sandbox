import { createChecker, nextUrl } from './helpers.ts';

/**
 * S12：SSG・ISR・SSR で「HTML がいつ作られたか」が違うことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session12/verify-modes.ts
 * 同じページを続けて2回取得し、埋め込まれた生成時刻が同じか違うかで判定する（決定的）。
 */
const { check, finish } = createChecker();

async function renderedAt(path: string): Promise<{ at: string | null; cacheControl: string | null }> {
  const res = await fetch(nextUrl(path));
  const html = await res.text();
  return {
    at: html.match(/<time id="rendered-at">([^<]+)<\/time>/)?.[1] ?? null,
    cacheControl: res.headers.get('cache-control'),
  };
}

for (const [path, label, expectSame] of [
  ['s12-ssg', 'SSG', true],
  ['s12-isr', 'ISR（revalidate = 3600）', true],
  ['s12-ssr', 'SSR（force-dynamic）', false],
] as const) {
  const first = await renderedAt(path);
  await new Promise((r) => setTimeout(r, 50));
  const second = await renderedAt(path);
  console.log(`${label}: 1回目 ${first.at} / 2回目 ${second.at} / Cache-Control: ${second.cacheControl}`);
  const same = first.at !== null && first.at === second.at;
  check(
    `${label}：2回の取得で生成時刻が${expectSame ? '同じ（作り置きを返す）' : '違う（毎回作る）'}`,
    first.at !== null && second.at !== null && same === expectSame,
  );
}

finish('S12 のレンダリング方式');
