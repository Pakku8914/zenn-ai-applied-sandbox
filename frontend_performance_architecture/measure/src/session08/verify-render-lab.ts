import type { Page } from 'playwright';
import { withPage } from '../vitals-client.ts';
import { diffCounts, readCounts, type Counts } from './render-count.ts';

/**
 * S08：再レンダリングの4つの条件と、「再レンダリング ≠ DOM 更新」を実験室ページで確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session08/verify-render-lab.ts
 * 本番ビルド（preview）と開発サーバーの両方で同じ操作をし、
 *   - 手動カウンタの回数はどちらでも表のとおり（完全一致）
 *   - <Profiler> の onRender は本番ビルドでは 0 回、開発サーバーでは 1 回以上
 * であることを判定する。回数だけを見るので、時間の計測はしない。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const DEV = process.env.DEV_URL ?? 'http://app.test:5173';
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

const PARTS = ['lab', 'plain', 'memoPlain', 'countLabel', 'themeLabel', 'selfCounter'] as const;
const DOM_PARTS = ['plain', 'memo-plain', 'count', 'theme'] as const;

type Scenario = { button: string; label: string; expect: Record<(typeof PARTS)[number], number> };

// 1回クリックしたときに、各コンポーネントの本体が何回実行されるか
const SCENARIOS: Scenario[] = [
  { button: '#bump-count', label: 'props が変わる（count）', expect: { lab: 1, plain: 1, memoPlain: 0, countLabel: 1, themeLabel: 0, selfCounter: 1 } },
  { button: '#toggle-theme', label: 'context が変わる（テーマ）', expect: { lab: 1, plain: 1, memoPlain: 0, countLabel: 0, themeLabel: 1, selfCounter: 1 } },
  { button: '#parent-only', label: '親の state だけが変わる', expect: { lab: 1, plain: 1, memoPlain: 0, countLabel: 0, themeLabel: 0, selfCounter: 1 } },
  { button: '#self-state', label: '子が自分の state を変える', expect: { lab: 0, plain: 0, memoPlain: 0, countLabel: 0, themeLabel: 0, selfCounter: 1 } },
];

type LabResult = { renders: Counts[]; mutations: Record<string, number>[]; profilerOnRender: number };

declare global {
  interface Window {
    __s08Mutations?: Record<string, number>;
  }
}

async function runLab(page: Page, base: string): Promise<LabResult> {
  // 開発サーバーは開発版の React を圧縮せずに配信するので、絞ったネットワークでは読み込みに時間がかかる
  await page.goto(`${base}/pages/s08-render-lab/`, { waitUntil: 'load', timeout: 60_000 });
  await page.locator('#self-state').waitFor({ timeout: 60_000 });

  // data-part ごとに、その要素の中で起きた DOM の変更（文字・子要素・属性）を数える
  await page.evaluate((parts) => {
    const counts: Record<string, number> = {};
    window.__s08Mutations = counts;
    for (const part of parts) {
      counts[part] = 0;
      const el = document.querySelector(`[data-part="${part}"]`);
      if (!el) throw new Error(`[data-part="${part}"] が見つかりません`);
      new MutationObserver((records) => {
        counts[part] = (counts[part] ?? 0) + records.length;
      }).observe(el, { subtree: true, childList: true, characterData: true, attributes: true });
    }
  }, DOM_PARTS);

  const renders: Counts[] = [];
  const mutations: Record<string, number>[] = [];
  for (const s of SCENARIOS) {
    const before = await readCounts(page);
    const domBefore = await page.evaluate(() => ({ ...(window.__s08Mutations ?? {}) }));
    await page.click(s.button);
    await page.waitForTimeout(300);
    renders.push(diffCounts(before, await readCounts(page)));
    const domAfter = await page.evaluate(() => ({ ...(window.__s08Mutations ?? {}) }));
    mutations.push(Object.fromEntries(DOM_PARTS.map((p) => [p, (domAfter[p] ?? 0) - (domBefore[p] ?? 0)])));
  }
  return { renders, mutations, profilerOnRender: (await readCounts(page)).profilerOnRender ?? 0 };
}

const prod = await withPage((page) => runLab(page, TARGET));
const dev = await withPage((page) => runLab(page, DEV));

console.log('1回クリックしたときの、本体の実行回数（本番ビルド）');
SCENARIOS.forEach((s, i) => {
  const r = prod.renders[i]!;
  console.log(`${s.label}: ${PARTS.map((p) => `${p} ${r[p] ?? 0}`).join(' / ')}`);
});
console.log('');

SCENARIOS.forEach((s, i) => {
  for (const [label, result] of [['本番ビルド', prod], ['開発サーバー', dev]] as const) {
    const r = result.renders[i]!;
    const got = PARTS.map((p) => r[p] ?? 0);
    const want = PARTS.map((p) => s.expect[p]);
    check(`${label}: ${s.label} の実行回数が表のとおり`, got.join(',') === want.join(','), got.join(','));
  }
});

// 再レンダリングと DOM 更新は別物：実行されても、出力が同じなら DOM は触られない
const parentOnly = SCENARIOS.findIndex((s) => s.button === '#parent-only');
const bump = SCENARIOS.findIndex((s) => s.button === '#bump-count');
check(
  '親だけの state を変えると、plain は実行されるが DOM の変更は 0 件',
  prod.renders[parentOnly]!.plain === 1 && prod.mutations[parentOnly]!.plain === 0,
  `実行 ${prod.renders[parentOnly]!.plain} 回 / DOM 変更 ${prod.mutations[parentOnly]!.plain} 件`,
);
check(
  'count を増やすと、count の表示だけ DOM が変わる（plain・theme は 0 件）',
  prod.mutations[bump]!.count! > 0 && prod.mutations[bump]!.plain === 0 && prod.mutations[bump]!.theme === 0,
  JSON.stringify(prod.mutations[bump]),
);

// Profiler の onRender は本番ビルドでは呼ばれない。手動カウンタを使う理由
check('本番ビルドでは Profiler の onRender が 0 回', prod.profilerOnRender === 0, `${prod.profilerOnRender} 回`);
check('開発サーバーでは Profiler の onRender が 1 回以上', dev.profilerOnRender > 0, `${dev.profilerOnRender} 回`);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS08 の再レンダリング条件の検証に成功しました。');
