import type { Page } from 'playwright';
import { collectVitals, interactAndCollect, withPage } from '../vitals-client.ts';
import { KEYWORD, TARGET, createChecker, matchedFor, n, waitForCount } from './helpers.ts';

/**
 * S11：全件描画と仮想化で、DOM に置かれる行と要素の数を比べる。値はすべて決定的なので完全一致で判定する。
 * 実行: docker compose exec measure node --experimental-strip-types src/session11/verify-dom.ts
 *
 * 要素数は #root の中だけを数える。document 全体の数には <head> 内の要素（ビルドが挿入する
 * <link rel="modulepreload"> など）が含まれ、ページの追加でチャンク構成が変わると増減するため。
 */
const ROW_HEIGHT = 40;
const MAX_ROWS = 21; // ceil(400 / 40) + 1 + オーバースキャン 5 × 2
const { check, finish } = createChecker();

type Snapshot = {
  li: number;
  rootNodes: number;
  first: string;
  last: string;
  posinset: string | null;
  setsize: string | null;
  scrollHeight: number;
  /** ページ内検索（Ctrl+F / Cmd+F）の対象になる文字列に「商品1500」が含まれるか */
  has1500: boolean;
};

async function snapshot(page: Page): Promise<Snapshot> {
  return page.evaluate(() => {
    const items = document.querySelectorAll('section ul li');
    const firstLi = items[0];
    const lastLi = items[items.length - 1];
    return {
      li: items.length,
      rootNodes: document.querySelectorAll('#root *').length,
      first: firstLi?.querySelector('span')?.textContent ?? '',
      last: lastLi?.querySelector('span')?.textContent ?? '',
      posinset: firstLi?.getAttribute('aria-posinset') ?? null,
      setsize: firstLi?.getAttribute('aria-setsize') ?? null,
      scrollHeight: document.querySelector('[data-viewport]')?.scrollHeight ?? 0,
      has1500: document.body.innerText.includes('商品1500'),
    };
  });
}

/** 表示枠の scrollTop を設定し、描画が追いつくのを待ってから読む。待ちきれなければそのまま読み、判定で NG にする */
async function scrollAndRead(page: Page, top: number, want: { first: string; li: number }): Promise<Snapshot> {
  await page.locator('[data-viewport]').evaluate((el, t) => {
    el.scrollTop = t;
  }, top);
  try {
    await page.waitForFunction(
      ({ first, li }) =>
        document.querySelectorAll('section ul li').length === li &&
        document.querySelector('section ul li span')?.textContent === first,
      want,
      { timeout: 5_000 },
    );
  } catch {
    // 下の check で NG として報告する
  }
  return snapshot(page);
}

async function typeAndRead(page: Page, total: number): Promise<Snapshot> {
  await interactAndCollect(page, '#keyword', KEYWORD);
  try {
    await waitForCount(page, matchedFor(total));
  } catch {
    // 下の check で NG として報告する
  }
  return snapshot(page);
}

const log = (label: string, s: Snapshot): void =>
  console.log(`${label}: li ${n(s.li)} / #root 内の要素 ${n(s.rootNodes)} / 先頭 ${s.first}`);

// --- 全件描画版 ---
for (const total of [2_000, 20_000]) {
  const name = `s11-plain-${total / 1000}k`;
  await withPage(async (page) => {
    await collectVitals(page, `${TARGET}/pages/${name}/`);
    const s = await snapshot(page);
    log(name, s);
    check(`${name}: 全 ${n(total)} 行が DOM にある`, s.li === total, n(s.li));
    check(`${name}: #root 内の要素が 8 + 4 × ${n(total)} = ${n(8 + 4 * total)}`, s.rootNodes === 8 + 4 * total, n(s.rootNodes));
    check(`${name}: 表示枠の scrollHeight が ${n(total * ROW_HEIGHT)}px`, s.scrollHeight === total * ROW_HEIGHT, n(s.scrollHeight));
    check(`${name}: ページ内検索の対象に「商品1500」が含まれる`, s.has1500);

    const typed = await typeAndRead(page, total);
    log(`${name}（「${KEYWORD}」入力後）`, typed);
    check(`${name}: 絞り込み後は ${n(matchedFor(total))} 行が DOM にある`, typed.li === matchedFor(total), n(typed.li));
  });
}

// --- 仮想化版 ---
const liByPosition: Record<string, number[]> = {};
for (const total of [2_000, 20_000]) {
  const name = `s11-virtual-${total / 1000}k`;
  const counts: number[] = [];
  await withPage(async (page) => {
    await collectVitals(page, `${TARGET}/pages/${name}/`);

    const top = await snapshot(page);
    log(`${name} 先頭`, top);
    counts.push(top.li);
    check(`${name}: 先頭では 15 行だけが DOM にある`, top.li === 15, n(top.li));
    check(`${name}: 先頭では #root 内の要素が 10 + 4 × 15 = 70`, top.rootNodes === 70, n(top.rootNodes));
    check(`${name}: 先頭の行は 商品1（aria-posinset=1）`, top.first === '商品1' && top.posinset === '1', `${top.first} / ${top.posinset}`);
    check(`${name}: aria-setsize が全件数 ${total}`, top.setsize === String(total), String(top.setsize));
    check(`${name}: スペーサー込みの scrollHeight が全件分の ${n(total * ROW_HEIGHT)}px`, top.scrollHeight === total * ROW_HEIGHT, n(top.scrollHeight));
    check(`${name}: ページ内検索の対象に「商品1500」が含まれない（DOM に無い）`, !top.has1500);

    const positions = [
      { label: '4,000px', top: 4_000, first: '商品96', li: 20 },
      { label: '4,020px', top: 4_020, first: '商品96', li: 21 },
      { label: '末尾', top: 1e9, first: `商品${total - 14}`, li: 15 },
    ];
    for (const p of positions) {
      const s = await scrollAndRead(page, p.top, p);
      log(`${name} ${p.label}`, s);
      counts.push(s.li);
      check(`${name} ${p.label}: 先頭の行が ${p.first}・行数 ${p.li}`, s.first === p.first && s.li === p.li, `${s.first} / ${s.li}`);
      check(`${name} ${p.label}: #root 内の要素が 10 + 4 × 行数`, s.rootNodes === 10 + 4 * s.li, n(s.rootNodes));
      check(`${name} ${p.label}: 行数が上限 ${MAX_ROWS} 以下`, s.li <= MAX_ROWS, n(s.li));
      if (p.label === '4,000px') check(`${name} 4,000px: 先頭の行の aria-posinset が 96`, s.posinset === '96', String(s.posinset));
      if (p.label === '末尾') check(`${name} 末尾: 最後の行が 商品${total}`, s.last === `商品${total}`, s.last);
    }

    // 先頭に戻してから絞り込む
    await scrollAndRead(page, 0, { first: '商品1', li: 15 });
    const typed = await typeAndRead(page, total);
    log(`${name}（「${KEYWORD}」入力後）`, typed);
    check(`${name}: 絞り込み後も DOM にあるのは 15 行`, typed.li === 15, n(typed.li));
    check(`${name}: 絞り込み後の aria-setsize が ${matchedFor(total)}`, typed.setsize === String(matchedFor(total)), String(typed.setsize));
  });
  liByPosition[name] = counts;
}

const small = liByPosition['s11-virtual-2k'] ?? [];
const large = liByPosition['s11-virtual-20k'] ?? [];
check(
  '20,000 件でも、同じ位置で DOM に置く行の数は 2,000 件と同じ',
  small.length === 4 && small.join(',') === large.join(','),
  `${small.join('/')} と ${large.join('/')}`,
);

finish('S11 の DOM ノード数');
