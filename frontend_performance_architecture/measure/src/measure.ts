import { collectVitals, CONDITIONS, interactAndCollect, withPage } from './vitals-client.ts';

const TARGET = process.env.TARGET_URL ?? 'http://preview.test:4173';

/** 計測結果を表で出力する。本文に載せる数値はこの出力から転記する。 */
const vitals = await withPage(async (page) => {
  // まず LCP・CLS・TTFB を取る（入力より先に行う。順序を変えると LCP が取れない）
  await collectVitals(page, TARGET);
  // 入力応答（INP）は実際に操作しないと出ないので、絞り込み入力を1回行う
  return interactAndCollect(page, '#keyword', '商品1');
});

console.log(`計測対象: ${TARGET}`);
console.log(
  `計測条件: CPU ${CONDITIONS.cpuThrottlingRate}x スロットリング / ` +
    `${CONDITIONS.network.downloadKbps}kbps / RTT ${CONDITIONS.network.latencyMs}ms`,
);
console.log('');
console.table(vitals);
