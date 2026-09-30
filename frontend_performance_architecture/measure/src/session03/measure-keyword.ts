import { collectVitals, interactAndCollect, withPage, type Vital } from '../vitals-client.ts';

/**
 * 絞り込み入力の応答（INP）まで含めて計測する。
 * 順序が要点：① 標準条件で開く → ② LCP を先に取る → ③ 実際のキー入力で INP を出す。
 */
export async function measureKeywordInput(url: string, keyword = '商品1'): Promise<Vital[]> {
  return withPage(async (page) => {
    await collectVitals(page, url);
    return interactAndCollect(page, '#keyword', keyword);
  });
}
