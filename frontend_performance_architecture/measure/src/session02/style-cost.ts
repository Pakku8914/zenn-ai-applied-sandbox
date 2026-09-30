import type { Page } from 'playwright';
import { median } from '../vitals-client.ts';

export type StyleCost = { layout: number; paint: number; composite: number };

/**
 * 商品リスト（section ul）のプロパティを1つ書き換え、直後に offsetHeight を読んで
 * ブラウザにその場で計算させる。書き換えから読み取りまでの時間を「その変更の計算コスト」とみなす。
 * ペイントと合成はこのあとフレームの中で行われるため、ここで測れるのはスタイル計算とレイアウトまで。
 */
export async function measureStyleCost(page: Page, samples = 7): Promise<StyleCost> {
  const raw = await page.evaluate((n) => {
    const ul = document.querySelector<HTMLElement>('section ul');
    if (!ul) throw new Error('section ul が見つかりません');

    // 初期値をそろえ、計算をいったん済ませておく（none → transform の初回だけ重くなるのを避ける）
    ul.style.width = '900px';
    ul.style.backgroundColor = '#ffffff';
    ul.style.transform = 'translateX(0px)';
    void ul.offsetHeight;

    const run = (apply: (i: number) => void): number[] => {
      const result: number[] = [];
      for (let i = 0; i < n; i += 1) {
        void ul.offsetHeight;
        const start = performance.now();
        apply(i);
        void ul.offsetHeight; // 読み取りで、保留中の計算をその場で行わせる
        result.push(performance.now() - start);
      }
      return result;
    };

    const measured = {
      layout: run((i) => {
        ul.style.width = i % 2 === 0 ? '600px' : '900px';
      }),
      paint: run((i) => {
        ul.style.backgroundColor = i % 2 === 0 ? '#fffbe6' : '#ffffff';
      }),
      composite: run((i) => {
        ul.style.transform = i % 2 === 0 ? 'translateX(4px)' : 'translateX(0px)';
      }),
    };

    // 画面を元に戻す
    ul.style.width = '';
    ul.style.backgroundColor = '';
    ul.style.transform = '';
    return measured;
  }, samples);

  return { layout: median(raw.layout), paint: median(raw.paint), composite: median(raw.composite) };
}
