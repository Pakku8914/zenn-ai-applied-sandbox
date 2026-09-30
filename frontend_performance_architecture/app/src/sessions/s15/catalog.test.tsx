import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { App } from '../../App';
import { ProductList } from '../../components/ProductList';
import { countRole, textOf, textsOf } from './visible';

// 出発点の画面を、利用者に見えるもの（テキスト・役割・件数）だけで検査する
describe('商品カタログの初期表示', () => {
  const html = renderToStaticMarkup(<App />);

  it('見出しが2つ並ぶ', () => {
    expect(textsOf(html, 'heading')).toEqual(['商品カタログ（計測用）', '商品一覧（2000 件）']);
  });

  it('入力欄が1つ、ボタンは「グラフを表示」の1つ', () => {
    expect(countRole(html, 'textbox')).toBe(1);
    expect(textsOf(html, 'button')).toEqual(['グラフを表示']);
  });

  it('全 2,000 件が並ぶ（グラフは押すまで出ない）', () => {
    expect(countRole(html, 'listitem')).toBe(2000);
    expect(html).not.toContain('<svg');
  });
});

describe('キーワードで絞り込んだ一覧', () => {
  const html = renderToStaticMarkup(<ProductList keyword="商品10" />);
  const items = textsOf(html, 'listitem');

  it('件数が見出しと行数の両方で 111 件', () => {
    expect(textOf(html)).toContain('商品一覧（111 件）');
    expect(items).toHaveLength(111);
  });

  it('先頭と末尾の行に名前・価格・カテゴリが見える', () => {
    expect(items[0]).toBe('商品10 470 円 雑貨');
    expect(items.at(-1)).toBe('商品1099 1163 円 食品');
  });

  it('一致しないキーワードでは 0 件', () => {
    const none = renderToStaticMarkup(<ProductList keyword="該当なし" />);
    expect(textOf(none)).toContain('商品一覧（0 件）');
    expect(countRole(none, 'listitem')).toBe(0);
  });
});
