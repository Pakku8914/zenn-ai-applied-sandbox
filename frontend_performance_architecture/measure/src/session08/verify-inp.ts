import { CONDITIONS, median, withPage } from '../vitals-client.ts';
import { INP_REPORT_THRESHOLD_MS, KEYWORD, ms, n, typeAndCount, type TypingRun } from './render-count.ts';

/**
 * S08：#keyword に「商品1」を入力したときの INP と再レンダリング回数を、7ページ×3回で比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session08/verify-inp.ts
 * 再レンダリング回数・行数は完全一致で、INP は大小関係と比率で判定する。
 */
const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';
const RUNS = 3;
const failures: string[] = [];

function check(name: string, ok: boolean, detail = ''): void {
  console.log(`${ok ? 'OK  ' : 'NG  '}${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

type Page = {
  name: string;
  total: number;
  /** 「商品1」を含む件数（入力後の行数） */
  matched: number;
  expect: { rowsWhileTyping: number; rowsWhileSelecting: number };
};

type Summary = { inp: number; unreported: number; runs: TypingRun[] };

// 「商」「商品」の2文字では全件が残り、「商品1」で 20,000 件 → 11,111 件（2,000 件 → 1,111 件）に絞られる
const PAGES: Page[] = [
  { name: 's08-bad-20k', total: 20_000, matched: 11_111, expect: { rowsWhileTyping: 51_111, rowsWhileSelecting: 22_222 } },
  { name: 's08-memo-inline-20k', total: 20_000, matched: 11_111, expect: { rowsWhileTyping: 51_111, rowsWhileSelecting: 22_222 } },
  { name: 's08-memo-20k', total: 20_000, matched: 11_111, expect: { rowsWhileTyping: 0, rowsWhileSelecting: 3 } },
  { name: 's08-deferred-20k', total: 20_000, matched: 11_111, expect: { rowsWhileTyping: 0, rowsWhileSelecting: 3 } },
  { name: 's08-transition-20k', total: 20_000, matched: 11_111, expect: { rowsWhileTyping: 0, rowsWhileSelecting: 3 } },
  { name: 's08-bad-2k', total: 2_000, matched: 1_111, expect: { rowsWhileTyping: 5_111, rowsWhileSelecting: 2_222 } },
  { name: 's08-memo-2k', total: 2_000, matched: 1_111, expect: { rowsWhileTyping: 0, rowsWhileSelecting: 3 } },
];

async function measurePage(p: Page): Promise<Summary> {
  const runs: TypingRun[] = [];
  for (let i = 0; i < RUNS; i += 1) {
    runs.push(await withPage((page) => typeAndCount(page, `${TARGET}/pages/${p.name}/`, p.matched)));
  }
  // 40ms 未満で報告されなかった回は、上限の 40ms として数える（改善版に有利にならない側に倒す）
  const inp = median(runs.map((r) => r.inp ?? INP_REPORT_THRESHOLD_MS));
  const unreported = runs.filter((r) => r.inp === null).length;
  const r0 = runs[0]!;
  console.log(
    `${p.name.padEnd(19)}: 入力 INP ${ms(inp)}${unreported > 0 ? `（${unreported}回は40ms未満で未報告）` : ''}` +
      ` / 行の実行 初回 ${n(r0.rowsOnMount)}・入力中 ${n(r0.rowsWhileTyping)}・選択2回 ${n(r0.rowsWhileSelecting)}` +
      ` / 入力後の行数 ${n(r0.liAfter)}`,
  );
  return { inp, unreported, runs };
}

const { cpuThrottlingRate, network } = CONDITIONS;
console.log(
  `計測条件: CPU ${cpuThrottlingRate}倍スロットリング / ${network.downloadKbps.toLocaleString('en-US')}kbps / RTT ${network.latencyMs}ms / 本番ビルド（各${RUNS}回の中央値）`,
);
console.log(`入力: #keyword に「${KEYWORD}」（pressSequentially）`);

const results = new Map<string, Summary>();
for (const p of PAGES) results.set(p.name, await measurePage(p));
console.log('');

// 決定的な値は完全一致（3回すべて）
for (const p of PAGES) {
  const s = results.get(p.name)!;
  const allOk = (pick: (r: TypingRun) => number, want: number) => s.runs.every((r) => pick(r) === want);
  check(`${p.name}: 初回は全 ${n(p.total)} 行を1回ずつ実行する`, allOk((r) => r.rowsOnMount, p.total));
  check(
    `${p.name}: 入力中の行の実行が ${n(p.expect.rowsWhileTyping)} 回`,
    allOk((r) => r.rowsWhileTyping, p.expect.rowsWhileTyping),
    s.runs.map((r) => n(r.rowsWhileTyping)).join(' / '),
  );
  check(
    `${p.name}: 行を2回選ぶ間の行の実行が ${n(p.expect.rowsWhileSelecting)} 回`,
    allOk((r) => r.rowsWhileSelecting, p.expect.rowsWhileSelecting),
    s.runs.map((r) => n(r.rowsWhileSelecting)).join(' / '),
  );
  check(`${p.name}: 入力後の行数が ${n(p.matched)}`, allOk((r) => r.liAfter, p.matched));
}

const inp = (name: string): number => results.get(name)!.inp;
const bad20k = inp('s08-bad-20k');
const bad2k = inp('s08-bad-2k');
const memo20k = inp('s08-memo-20k');
const memo2k = inp('s08-memo-2k');

// 時間は大小関係と比率で判定する
check('Bad 版（20,000 件）の入力 INP が 200ms 以上（good の境界を超えている）', bad20k >= 200, ms(bad20k));
check('Bad 版は 20,000 件のほうが 2,000 件より INP が大きい', bad20k > bad2k, `${ms(bad2k)} → ${ms(bad20k)}`);
check('メモ化版（20,000 件）の INP が Bad 版より小さい', memo20k < bad20k, `${(memo20k / bad20k).toFixed(2)} 倍`);
check(
  'memo だけの版（関数を毎回作る）はメモ化版より INP が大きい',
  inp('s08-memo-inline-20k') > memo20k,
  `${ms(inp('s08-memo-inline-20k'))} / ${ms(memo20k)}`,
);
for (const name of ['s08-deferred-20k', 's08-transition-20k']) {
  const ratio = inp(name) / bad20k;
  check(`${name} の INP 中央値が Bad 版の 0.5 倍以下`, ratio <= 0.5, `${ratio.toFixed(2)} 倍`);
}

// メモ化を入れない判断の材料：2,000 件では既に good で、メモ化で縮む幅も 20,000 件より小さい
check('Bad 版（2,000 件）の入力 INP は 200ms 未満（good 域）', bad2k < 200, ms(bad2k));
const gain2k = bad2k - memo2k;
const gain20k = bad20k - memo20k;
check('メモ化で縮む INP の幅は、2,000 件のほうが 20,000 件より小さい', gain2k < gain20k, `${ms(gain2k)} < ${ms(gain20k)}`);

if (failures.length > 0) {
  console.error(`\n検証に失敗しました（${failures.length}件）: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nS08 の入力 INP と再レンダリング回数の検証に成功しました。');
