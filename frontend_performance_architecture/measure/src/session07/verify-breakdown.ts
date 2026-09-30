import { collectVitals, withPage } from '../vitals-client.ts';
import { clickAndCollect, installRecorders, ms, readRun, type Breakdown } from './click-inp.ts';

/**
 * S07：INP の内訳（入力遅延・処理時間・表示遅延）が、原因によって入れ替わることを確かめる。
 *   (1) 出発点：クリックの処理そのものが重い → 処理時間がいちばん大きい
 *   (2) タスク分割版でも、クリックした瞬間に別の長いタスク（300ms）が走っていれば → 入力遅延がいちばん大きい
 * 実行: docker compose exec measure node --experimental-strip-types src/session07/verify-breakdown.ts
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const BUSY_MS = 300;
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const show = (label: string, b: Breakdown | null): void => {
  console.log(
    `${label}: ${b ? `入力遅延 ${ms(b.inputDelay)} / 処理時間 ${ms(b.processing)} / 表示遅延 ${ms(b.presentation)}（合計 ${ms(b.duration)}）` : '記録なし'}`,
  );
};

// (1) 出発点をふつうにクリックする
const heavy = await withPage((page) => clickAndCollect(page, `${TARGET}/pages/s07-baseline/`));

// (2) タスク分割版で、別の長いタスクが走っている最中にクリックする
const busy = await withPage(async (page) => {
  await collectVitals(page, `${TARGET}/pages/s07-chunked/`);
  await installRecorders(page);
  const box = await page.locator('button').boundingBox();
  if (!box) throw new Error('ボタンが見つかりません');

  // 画面とは無関係な長いタスクを 1 つ予約する（例：解析タグや別の部品の初期化）
  await page.evaluate((busyMs) => {
    setTimeout(() => {
      const start = performance.now();
      while (performance.now() - start < busyMs) {
        // メインスレッドを占有する
      }
    }, 0);
  }, BUSY_MS);
  await page.waitForTimeout(30);
  // page.click() は押す前にページ内で JS を動かして要素の状態を確かめるため、長いタスクが終わるまで押せない。
  // 長いタスクの最中に押すには、座標を指定して直接マウスを動かす
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.locator('figure polyline').waitFor({ timeout: 15_000 });
  await page.waitForTimeout(2_000);
  return readRun(page);
});

show('(1) 出発点をクリック          ', heavy.breakdown);
show(`(2) ${BUSY_MS}ms のタスク中にクリック`, busy.breakdown);
console.log('');

const h = heavy.breakdown;
check('(1) 内訳が記録されている', h !== null);
if (h) {
  check('(1) 処理時間が入力遅延より大きい', h.processing > h.inputDelay);
  check('(1) 処理時間が表示遅延より大きい', h.processing > h.presentation);
}
const d = busy.breakdown;
check('(2) 内訳が記録されている', d !== null);
if (d) {
  check('(2) 入力遅延が処理時間より大きい', d.inputDelay > d.processing);
  check('(2) 入力遅延が表示遅延より大きい', d.inputDelay > d.presentation);
  check(`(2) 入力遅延が ${BUSY_MS}ms の 3 分の 1 以上`, d.inputDelay >= BUSY_MS / 3, ms(d.inputDelay));
}

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS07 の INP 内訳の検証に成功しました。');
