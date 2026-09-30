import {
  CLS_RUNS,
  DONE,
  MATCHED,
  RUNS,
  START,
  TABLE_HEADER,
  TOTAL,
  conditionsLabel,
  createChecker,
  formatRow,
  measurePage,
  ms,
  n,
} from './helpers.ts';

/**
 * 最終プロジェクト：出題版と模範解答版を同じ条件で測り、読み込み・描画・入力応答・DOM の大きさが改善したことを確かめる。
 * 実行: docker compose exec measure node --experimental-strip-types src/final/verify-vitals.ts
 * 行数・DOM ノード数・初期 JS は決定的なので完全一致と予算との大小で、時間の指標は比率と大小関係で判定する。
 */
const { check, finish } = createChecker();

console.log(`計測条件: ${conditionsLabel()}（LCP・INP・初期 JS は各${RUNS}回、CLS は各${CLS_RUNS}回の中央値）`);
console.log(`入力: #keyword に「商品1」（pressSequentially）／クリック: 「グラフを表示」\n`);

const start = await measurePage(START);
const done = await measurePage(DONE);
console.log(TABLE_HEADER);
console.log(formatRow('final-start', start));
console.log(formatRow('final-done', done));
console.log('');

const ratio = (after: number, before: number): string => `${(after / before).toFixed(2)} 倍`;
const domText = (d: { rows: number; nodes: number }): string => `${n(d.rows)} 行 / ${n(d.nodes)} 個`;

// 1. 決定的な値（完全一致）。出題版は 1 行が li・button・span・span の 4 要素 ＋ 行以外の 10 要素
check(
  `出題版: 開いた直後は ${n(TOTAL)} 行・DOM ノード 80,010 個`,
  start.opened.rows === TOTAL && start.opened.nodes === 80_010,
  domText(start.opened),
);
check(
  `出題版: 入力後は ${n(MATCHED)} 行・DOM ノード 44,454 個（3 回とも）`,
  start.typedRuns.every((d) => d.rows === MATCHED && d.nodes === 44_454),
  start.typedRuns.map(domText).join(' / '),
);
// 模範解答版は表示枠 400px ÷ 行 40px ＝ 10 行 ＋ 下のオーバースキャン 5 行 ＝ 15 行。行以外は 13 要素
check(
  '模範解答版: 開いた直後も入力後も 15 行・DOM ノード 73 個',
  done.opened.rows === 15 && done.opened.nodes === 73 && done.typedRuns.every((d) => d.rows === 15 && d.nodes === 73),
  `${domText(done.opened)}（入力後 ${done.typedRuns.map(domText).join(' / ')}）`,
);
check(
  '初期 JS は 3 回とも同じ値（決定的）',
  new Set(start.jsRuns).size === 1 && new Set(done.jsRuns).size === 1,
  `${start.jsRuns.map(n).join(' / ')} ／ ${done.jsRuns.map(n).join(' / ')}`,
);

// 2. 読み込み：初期 JS と LCP
check('出題版の初期 JS は予算 250,000 バイトを超えている', start.jsBytes > 250_000, `${n(start.jsBytes)} バイト`);
check('模範解答版の初期 JS は予算 250,000 バイト以内', done.jsBytes <= 250_000, `${n(done.jsBytes)} バイト`);
const saved = start.jsBytes - done.jsBytes;
check('初期 JS の差は 100,000 バイト以上（印刷用の react-dom/server が初期 JS から外れた）', saved >= 100_000, `-${n(saved)} バイト`);
check('模範解答版の LCP 中央値が出題版の 0.7 倍以下', done.lcp <= start.lcp * 0.7, `${ms(start.lcp)} → ${ms(done.lcp)}（${ratio(done.lcp, start.lcp)}）`);
check('模範解答版の LCP 中央値が予算 1,000ms 以内', done.lcp <= 1_000, ms(done.lcp));

// 3. 入力応答：キー入力とクリック
check('出題版の入力 INP が 200ms 以上（good の境界を超えている）', start.inputInp >= 200, ms(start.inputInp));
check('模範解答版の入力 INP が 200ms 未満（good）', done.inputInp < 200, ms(done.inputInp));
check('模範解答版の入力 INP が出題版の 0.5 倍以下', done.inputInp <= start.inputInp * 0.5, ratio(done.inputInp, start.inputInp));
check('出題版のクリック INP が 200ms 以上', start.clickInp >= 200, ms(start.clickInp));
check('模範解答版のクリック INP が 200ms 未満（good）', done.clickInp < 200, ms(done.clickInp));
check('模範解答版のクリック INP が出題版の 0.5 倍以下', done.clickInp <= start.clickInp * 0.5, ratio(done.clickInp, start.clickInp));

// 4. 描画：後から出るバナーによるずれ
check('出題版の CLS 中央値が 0.1 以上（good の範囲を外れる）', start.cls >= 0.1, start.cls.toFixed(3));
check('模範解答版の CLS 中央値が 0.1 未満（good）', done.cls < 0.1, done.cls.toFixed(3));

finish('最終プロジェクトの計測');
