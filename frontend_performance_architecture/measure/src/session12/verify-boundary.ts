import { jsBytes, withPage } from '../vitals-client.ts';
import {
  SPA,
  createChecker,
  loadedScriptText,
  nextUrl,
  readHydration,
  readList,
  waitForHeading,
} from './helpers.ts';

/**
 * S12：サーバーとクライアントの境界を、葉に寄せた版（RSC 版）と根元に置いた版（全部クライアント版）で比べる。
 * 実行: docker compose exec measure node --experimental-strip-types src/session12/verify-boundary.ts
 * (1) 一覧の部品のコードがクライアントの JS に入るか  (2) 初期 JS のバイト数
 * (3) HTML が見えてから操作できるまでの差  (4) 入力で絞り込めるか（件数は完全一致）
 */
const { check, finish } = createChecker();
const MARKER = 's12-product-rows'; // next/lib/s12/ProductRows.tsx の data-component

type Observed = {
  initial: { heading: string | null; rows: number };
  hasRowsCode: boolean;
  bytes: number;
  fcp: number;
  hydratedAt: number;
  afterInput: { heading: string | null; rows: number };
  query: string | null;
};

async function observe(url: string): Promise<Observed> {
  return withPage(async (page) => {
    await page.goto(url, { waitUntil: 'load' });
    const { fcp, hydratedAt } = await readHydration(page);
    const initial = await readList(page);
    // loadedScriptText は JS を取り直すので resource エントリが増える。先に数える
    const bytes = await jsBytes(page);
    const hasRowsCode = (await loadedScriptText(page)).includes(MARKER);
    await page.locator('#keyword').pressSequentially('商品1', { delay: 60 });
    await waitForHeading(page, '商品一覧（1111 件）');
    const afterInput = await readList(page);
    return { initial, hasRowsCode, bytes, fcp, hydratedAt, afterInput, query: new URL(page.url()).searchParams.get('q') };
  });
}

const rsc = await observe(nextUrl('s12-rsc'));
const client = await observe(nextUrl('s12-client'));
const spa = await observe(SPA);

console.log('| 版 | 初期 JS | FCP | 操作できる時刻 | 差 |');
console.log('| :--- | ---: | ---: | ---: | ---: |');
for (const [label, o] of [['SPA 版', spa], ['全部クライアント版', client], ['RSC 版', rsc]] as const) {
  const gap = Math.round(o.hydratedAt - o.fcp);
  console.log(
    `| ${label} | ${o.bytes.toLocaleString('en-US')} バイト | ${Math.round(o.fcp)}ms | ${Math.round(o.hydratedAt)}ms | ${gap}ms |`,
  );
}
console.log('');

for (const [label, o] of [['SPA 版', spa], ['全部クライアント版', client], ['RSC 版', rsc]] as const) {
  check(`${label}：初期表示は「商品一覧（2000 件）」の 2000 行`, o.initial.heading === '商品一覧（2000 件）' && o.initial.rows === 2000);
  check(`${label}：「商品1」の入力で「商品一覧（1111 件）」の 1111 行`, o.afterInput.heading === '商品一覧（1111 件）' && o.afterInput.rows === 1111);
}
check('RSC 版：入力は URL の ?q= に反映される（一覧はサーバーが描き直す）', rsc.query === '商品1', `${rsc.query}`);
check(`RSC 版：一覧の部品（${MARKER}）はクライアントの JS に含まれない`, !rsc.hasRowsCode);
check(`全部クライアント版：一覧の部品（${MARKER}）がクライアントの JS に含まれる`, client.hasRowsCode);
check('初期 JS：RSC 版 < 全部クライアント版', rsc.bytes < client.bytes, `${rsc.bytes} < ${client.bytes}`);
check('全部クライアント版：HTML が見えた（FCP）あとで、ハイドレーションが終わる', client.fcp > 0 && client.fcp < client.hydratedAt);
check(
  '見えてから操作できるまでの差：全部クライアント版（SSR）> SPA 版',
  client.hydratedAt - client.fcp > spa.hydratedAt - spa.fcp,
);
check('FCP：全部クライアント版（SSR）< SPA 版（HTML に内容が入っている）', client.fcp < spa.fcp);

finish('S12 のサーバーとクライアントの境界');
