import { collectVitals, withPage } from '../vitals-client.ts';

/**
 * S15：E2E テストの例。本番ビルドを実際のブラウザで開き、利用者と同じ操作をして、利用者に見えるものを確かめる。
 * 要素は id やクラス名ではなく、役割（role）と名前（ラベル・文言）で探す。
 * 実行: docker compose exec measure node --experimental-strip-types src/session15/verify-e2e.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];
function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

await withPage(async (page) => {
  // 入力より先に LCP の報告を待つ（計測の契約。先に入力すると LCP が取れなくなる）
  await collectVitals(page, `${TARGET}/`);

  const items = page.getByRole('listitem');
  check('最初は 2,000 件が並ぶ', (await items.count()) === 2000, `${await items.count()} 件`);

  // ラベル「商品名で絞り込み」が付いた入力欄に、利用者と同じように1文字ずつ入力する
  await page.getByRole('textbox', { name: '商品名で絞り込み' }).pressSequentially('商品10', { delay: 60 });
  await page.getByRole('heading', { name: '商品一覧（111 件）' }).waitFor({ timeout: 15_000 });
  check('「商品10」で絞り込むと 111 件', (await items.count()) === 111, `${await items.count()} 件`);
  check('先頭の行は「商品10」', (await items.first().innerText()).includes('商品10'));

  const toggle = page.getByRole('button', { name: 'グラフを表示' });
  await toggle.click();
  await page.getByRole('button', { name: 'グラフを隠す' }).waitFor({ timeout: 15_000 });
  check('ボタンを押すと文言が「グラフを隠す」に変わる', true);
});

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS15 E2E の検証に成功しました。');
