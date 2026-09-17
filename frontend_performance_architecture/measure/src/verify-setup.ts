import { collectVitals, interactAndCollect, withPage } from './vitals-client.ts';

/**
 * サンドボックスの自己検証。
 * 「計測できる状態になっていること」だけを確認する（値の良し悪しは章で扱う）。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const result = await withPage(async (page) => {
  const vitals = await collectVitals(page, TARGET);

  const title = await page.title();
  check('計測対象（本番ビルド）のページを開ける', title === '計測対象アプリ', `title=${title}`);

  const items = await page.locator('section ul li').count();
  check('商品が 2,000 件描画されている', items === 2000, `${items} 件`);

  const lcp = vitals.find((v) => v.name === 'LCP');
  check('LCP が計測できている', lcp !== undefined && lcp.value > 0, `LCP=${lcp?.value ?? 'なし'}ms`);

  const ttfb = vitals.find((v) => v.name === 'TTFB');
  check('TTFB が計測できている', ttfb !== undefined, `TTFB=${ttfb?.value ?? 'なし'}ms`);

  // 絞り込み入力が効くこと（INP を測る章の前提）。入力は LCP を取得した後に行う
  const afterInput = await interactAndCollect(page, '#keyword', '商品10');
  const filtered = await page.locator('section ul li').count();
  check('絞り込みが機能する', filtered > 0 && filtered < 2000, `${filtered} 件`);

  const inp = afterInput.find((v) => v.name === 'INP');
  check('INP が計測できている', inp !== undefined, `INP=${inp?.value ?? 'なし'}ms`);

  return afterInput;
});

console.log('');
console.log('計測された Core Web Vitals:');
console.table(result);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nサンドボックスの自己検証に成功しました。');
