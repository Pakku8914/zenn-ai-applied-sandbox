import { collectVitals, interactAndCollect, withPage } from '../vitals-client.ts';
import { measureStyleCost } from './style-cost.ts';

/**
 * 練習問題6の解答：件数を変えながら、幅の変更（レイアウト）にかかる時間を測る。
 * 実行: docker compose exec measure node --experimental-strip-types src/session02/layout-scaling.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';

// 空文字は「絞り込まない」＝ 2,000 件。件数は products.ts の命名規則から決まる
const KEYWORDS = ['', '商品1', '商品10', '商品100'] as const;

const rows: { キーワード: string; 件数: number; 'レイアウトms': number; '1件あたりμs': number }[] = [];

for (const keyword of KEYWORDS) {
  // 1 条件ごとに新しいブラウザで開く（前の計測の影響を持ち越さない）
  const row = await withPage(async (page) => {
    await collectVitals(page, TARGET);
    if (keyword !== '') {
      await interactAndCollect(page, '#keyword', keyword);
    }
    const count = await page.locator('section ul li').count();
    const cost = await measureStyleCost(page, 9);
    return {
      キーワード: keyword === '' ? '（なし）' : keyword,
      件数: count,
      'レイアウトms': Math.round(cost.layout * 100) / 100,
      '1件あたりμs': Math.round((cost.layout / count) * 1000 * 10) / 10,
    };
  });
  rows.push(row);
}

console.table(rows);
