import { withPage } from '../vitals-client.ts';
import { createChecker, loadedScriptText, nextUrl, readHydration, streamTimeline } from './helpers.ts';

/**
 * S12 練習問題の解答（問題4・問題5）を確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session12/verify-practice.ts
 */
const { check, finish } = createChecker();
const STOCK = 600; // next/lib/s12/practice.ts の STOCK_DELAY_MS
const REVIEW = 1800; // 同 REVIEW_DELAY_MS

// 問題4：在庫（600ms）はレビュー（1,800ms）を待たずに届く
const t = await streamTimeline(nextUrl('s12-practice-stream'), {
  stockFallback: 'id="stock-fallback"',
  reviewsFallback: 'id="reviews-fallback"',
  stock: 'id="stock"',
  reviews: 'id="reviews"',
});
console.log(
  `最初のチャンク ${t.firstChunkMs}ms / 在庫 ${t.at.stock}ms / レビュー ${t.at.reviews}ms`,
);
const stockAt = t.at.stock ?? -1;
const reviewsAt = t.at.reviews ?? -1;
check(
  '問題4：2つの fallback は、どちらのデータも待たずに届く',
  (t.at.stockFallback ?? Infinity) < STOCK - 200 && (t.at.reviewsFallback ?? Infinity) < STOCK - 200,
);
check('問題4：在庫は 600ms のあと、レビューより先に届く', stockAt >= STOCK - 100 && stockAt < reviewsAt);
check('問題4：在庫とレビューの到着は 800ms 以上離れている（レビューに引きずられない）', reviewsAt - stockAt >= REVIEW - STOCK - 400);

// 問題5：カードの本体はクライアントの JS に入らず、ボタンだけが動く
await withPage(async (page) => {
  await page.goto(nextUrl('s12-practice-leaf'), { waitUntil: 'load' });
  await readHydration(page);
  const cards = await page.locator('[data-card="s12-practice-card"]').count();
  const buttons = await page.locator('button[data-favorite]').count();
  const hasCardCode = (await loadedScriptText(page)).includes('s12-practice-card');
  const button = page.locator('button[data-favorite="1"]');
  await button.click();
  const pressed = await button.getAttribute('aria-pressed');
  const text = await button.textContent();
  check('問題5：カード 20 枚・ボタン 20 個', cards === 20 && buttons === 20, `${cards} 枚 / ${buttons} 個`);
  check('問題5：カードの本体（s12-practice-card）はクライアントの JS に含まれない', !hasCardCode);
  check('問題5：押すと aria-pressed="true"・「お気に入り済み」になる', pressed === 'true' && text === 'お気に入り済み');
});

finish('S12 の練習問題');
