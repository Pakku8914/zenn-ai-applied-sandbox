import { collectVitals, interactAndCollect, withPage } from '../vitals-client.ts';
import { GOOD, createChecker, waitReady } from './helpers.ts';

/**
 * S16：絞り込みの件数がライブリージョン（role="status"）で何回・何と伝わるかを数える。
 * 入力は pressSequentially（1 文字 60ms 間隔）。書き換わった文を順に記録し、完全一致で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session16/verify-live.ts
 */
const { check, finish } = createChecker();

const NO_MATCH = '条件に一致する商品はありません。キーワードを短くするか、カテゴリを「すべて」に戻してください。';

const cases = [
  { label: 'デバウンスあり（300ms）', url: GOOD, value: '商品10', log: ['111 件見つかりました'], heading: '商品一覧（111 件）' },
  {
    label: 'デバウンスなし（?live=eager）',
    url: `${GOOD}?live=eager`,
    value: '商品10',
    log: ['2,000 件見つかりました', '1,111 件見つかりました', '111 件見つかりました'],
    heading: '商品一覧（111 件）',
  },
  { label: '一致なし（デバウンスあり）', url: GOOD, value: '商品0', log: [NO_MATCH], heading: '商品一覧（0 件）' },
];

for (const c of cases) {
  await withPage(async (page) => {
    await collectVitals(page, c.url);
    await waitReady(page, 'good');

    // ライブリージョンの中身が書き換わるたびに、その文を記録する（同じ文が続いたら 1 回と数える）
    await page.evaluate(() => {
      const region = document.querySelector('[role="status"]');
      const log: string[] = [];
      window.__statusLog = log;
      if (region === null) return;
      new MutationObserver(() => {
        const text = region.textContent ?? '';
        if (log[log.length - 1] !== text) log.push(text);
      }).observe(region, { childList: true, characterData: true, subtree: true });
    });

    await interactAndCollect(page, '#keyword', c.value); // 打ち終えてから 800ms 待つ（デバウンスの 300ms より長い）
    const log = await page.evaluate(() => window.__statusLog ?? []);
    const finalText = await page.getByRole('status').textContent();
    const heading = await page.locator('#list-heading').textContent();

    console.log(`${c.label}「${c.value}」: ${log.length} 回 — ${log.join(' / ')}`);
    check(`${c.label}: 書き換わりが ${c.log.length} 回`, log.length === c.log.length, `${log.length} 回`);
    check(`${c.label}: 伝わった文の並びが期待どおり`, log.join('|') === c.log.join('|'), log.join(' / '));
    check(`${c.label}: 最後に残る文が「${c.log[c.log.length - 1]}」`, finalText === c.log[c.log.length - 1], String(finalText));
    check(`${c.label}: 見出しは「${c.heading}」`, heading === c.heading, String(heading));
  });
}

finish('S16 のライブリージョン');
