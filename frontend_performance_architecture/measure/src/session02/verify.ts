import { collectVitals, jsBytes, withPage } from '../vitals-client.ts';
import { buildMilestones, lastJsEnd, readSnapshot, round1 } from './entries.ts';

/**
 * セッション2 の検証（その1）：performance エントリの読み方。
 * 時間の絶対値は環境で変わるため、判定は「件数」「順序」「一致」だけで行う。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const { snap, bytes } = await withPage(async (page) => {
  await collectVitals(page, TARGET);
  return { snap: await readSnapshot(page), bytes: await jsBytes(page) };
});

const nav = snap.navigation[0];
check('navigation エントリが1件ある', snap.navigation.length === 1, `${snap.navigation.length} 件`);
check('ナビゲーションの種類が navigate', nav?.type === 'navigate', `type=${nav?.type ?? 'なし'}`);

if (nav) {
  const order = [
    nav.requestStart,
    nav.responseStart,
    nav.responseEnd,
    nav.domInteractive,
    nav.domContentLoadedEventStart,
    nav.domComplete,
    nav.loadEventStart,
  ];
  check(
    'HTML の取得 → パース → DOMContentLoaded → load の順に進む',
    order.every((t, i) => i === 0 || order[i - 1]! <= t),
    order.map(round1).join(' ≤ '),
  );
}

const js = snap.resources.filter((r) => r.path.endsWith('.js'));
const jsTotal = js.reduce((sum, r) => sum + r.decodedBodySize, 0);
check('JS の resource エントリがある', js.length >= 1, `${js.length} 本`);
check(
  'resource エントリの展開後サイズの合計が jsBytes() と一致する',
  jsTotal === bytes,
  `${jsTotal.toLocaleString('en-US')} バイト / jsBytes()=${bytes.toLocaleString('en-US')} バイト`,
);

const jsEnd = lastJsEnd(snap);
check(
  'モジュールスクリプトは DOMContentLoaded より前に取得を終える',
  nav !== undefined && jsEnd <= nav.domContentLoadedEventStart,
  `JS 取得完了 ${round1(jsEnd)}ms / DOMContentLoaded 開始 ${round1(nav?.domContentLoadedEventStart ?? Number.NaN)}ms`,
);

const fcp = snap.paints.find((p) => p.name === 'first-contentful-paint');
const fp = snap.paints.find((p) => p.name === 'first-paint');
check('FCP の paint エントリがある', fcp !== undefined, `FCP=${round1(fcp?.startTime ?? Number.NaN)}ms`);
check(
  'FCP は JS の取得完了より後（body が空の SPA は JS が届くまで何も描けない）',
  fcp !== undefined && fcp.startTime >= jsEnd,
  `${round1(fcp?.startTime ?? Number.NaN)}ms ≥ ${round1(jsEnd)}ms`,
);
check(
  'first-paint は FCP より後にならない',
  fp === undefined || fcp === undefined || fp.startTime <= fcp.startTime,
  `first-paint=${round1(fp?.startTime ?? Number.NaN)}ms`,
);

console.log('');
console.log('ナビゲーション開始から FCP までの内訳:');
console.table(buildMilestones(snap));

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nセッション2（performance エントリ）の検証に成功しました。');
