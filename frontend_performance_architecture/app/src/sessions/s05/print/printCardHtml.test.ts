import { describe, expect, it } from 'vitest';
import { products } from '../../../data/products';
import { printCardHtml } from './printCardHtml';
import { renderPrintCard } from './renderPrintCard';

describe('printCardHtml（react-dom/server を使わない自作版）', () => {
  it('2,000 件すべてで renderToString 版と同じ HTML を返す', () => {
    for (const product of products) {
      expect(printCardHtml(product)).toBe(renderPrintCard(product));
    }
  });

  it('HTML として意味を持つ文字をエスケープする（タグとして解釈させない）', () => {
    const evil = { id: 0, name: '<img src=x onerror="alert(1)">', price: 100, category: "A&B's" };
    expect(printCardHtml(evil)).toBe(
      '<article class="print-card"><h2>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</h2>' +
        '<p>100 円</p><p>A&amp;B&#x27;s</p></article>',
    );
    expect(printCardHtml(evil)).toBe(renderPrintCard(evil));
  });
});
