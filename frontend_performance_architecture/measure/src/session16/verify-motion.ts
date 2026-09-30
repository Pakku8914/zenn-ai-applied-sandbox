import { withPage } from '../vitals-client.ts';
import { BAD, GOOD, createChecker, pressTab, tryWait, waitReady } from './helpers.ts';

/**
 * S16：prefers-reduced-motion を emulateMedia で切り替え、アニメーションが止まるかを getComputedStyle で確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session16/verify-motion.ts
 */
const { check, finish } = createChecker();

for (const reduce of [false, true]) {
  const label = reduce ? 'reduce' : 'no-preference';
  const expectGood = (name: string) => (reduce ? 'none' : name);

  await withPage(async (page) => {
    await page.emulateMedia({ reducedMotion: reduce ? 'reduce' : 'no-preference' });

    // スケルトン（読み込みを 10 秒に引き延ばして観察する）
    await page.goto(`${GOOD}?latency=10000`);
    await page.waitForSelector('[data-skeleton-bar]');
    const matches = await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
    const skeleton = await page.locator('[data-skeleton-bar]').first().evaluate((el) => getComputedStyle(el).animationName);
    check(`${label}: matchMedia の結果が ${reduce}`, matches === reduce, String(matches));
    check(`good ${label}: スケルトンの animation-name が ${expectGood('s16-pulse')}`, skeleton === expectGood('s16-pulse'), skeleton);

    // ダイアログ
    await page.goto(GOOD);
    await waitReady(page, 'good');
    await pressTab(page, 3);
    await page.keyboard.press('Enter');
    await tryWait(page, `document.querySelector('dialog')?.open === true`);
    const dialog = await page.locator('dialog').evaluate((el) => getComputedStyle(el).animationName);
    check(`good ${label}: ダイアログの animation-name が ${expectGood('s16-slide-in')}`, dialog === expectGood('s16-slide-in'), dialog);

    // Bad 版のスピナーは設定を見ない
    await page.goto(`${BAD}?latency=10000`);
    await page.waitForSelector('[data-spinner]');
    const spinner = await page.locator('[data-spinner]').evaluate((el) => getComputedStyle(el).animationName);
    check(`bad ${label}: スピナーは設定に関わらず s16-spin のまま`, spinner === 's16-spin', spinner);
  });
}

finish('S16 の prefers-reduced-motion');
