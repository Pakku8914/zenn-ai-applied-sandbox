import { withPage } from '../vitals-client.ts';
import { clickAndCollect, ms } from './click-inp.ts';

/**
 * S07：指定したページで「グラフを表示」を押し、そのあとに記録された長いフレームを長い順に表示する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session07/show-long-frames.ts s07-baseline
 * 判定はしない（観察用）。判定は verify-inp.ts が行う。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const pageName = process.argv[2] ?? 's07-baseline';

const run = await withPage((page) => clickAndCollect(page, `${TARGET}/pages/${pageName}/`));
const top = [...run.frames].sort((a, b) => b.duration - a.duration).slice(0, 3);

console.log(`${pageName}: クリック後の長いフレーム ${run.frames.length} 件（長い順に最大 3 件）`);
console.table(
  top.map((f) => ({
    種類: f.type,
    長さ: ms(f.duration),
    入力を待たせた時間: f.blockingDuration === null ? '（longtask では取れない）' : ms(f.blockingDuration),
    呼び出し元: f.invokers.join(', ') || '不明',
  })),
);
