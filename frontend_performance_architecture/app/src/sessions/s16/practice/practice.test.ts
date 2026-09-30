import { describe, expect, it } from 'vitest';
import { products } from '../../../data/products';
import { scrollTopToReveal } from '../a11yModel';
import { feedbackFor } from './feedback';
import { conditionMessage } from './messages';
import { scrollBehaviorFor } from './motion';
import { PAGE_SIZE, nextIndexWithPaging } from './paging';
import { renderIndicesMany } from './pins';

describe('問題2：条件を含む件数メッセージ', () => {
  const countOf = (keyword: string, category: string) =>
    products.filter((p) => p.name.includes(keyword) && (category === 'すべて' || p.category === category)).length;

  it('キーワードだけ・カテゴリだけ・両方・なし', () => {
    expect(conditionMessage(countOf('商品10', 'すべて'), 2000, '商品10', 'すべて')).toBe('「商品10」で 111 件見つかりました');
    expect(conditionMessage(countOf('', '文具'), 2000, '', '文具')).toBe('カテゴリ「文具」で 500 件見つかりました');
    expect(conditionMessage(countOf('商品10', '文具'), 2000, '商品10', '文具')).toBe('カテゴリ「文具」・「商品10」で 28 件見つかりました');
    expect(conditionMessage(2000, 2000, '', 'すべて')).toBe('全 2,000 件を表示しています');
  });

  it('0 件なら次の操作を添える', () => {
    expect(conditionMessage(countOf('商品0', 'すべて'), 2000, '商品0', 'すべて')).toBe('「商品0」に一致する商品はありません。条件を減らしてください。');
  });
});

describe('問題4：PageDown / PageUp', () => {
  it('表示枠 1 つぶん（10 行）動き、端で止まる', () => {
    expect(PAGE_SIZE).toBe(10);
    expect(nextIndexWithPaging(0, 'PageDown', 2000)).toBe(10);
    expect(nextIndexWithPaging(1995, 'PageDown', 2000)).toBe(1999);
    expect(nextIndexWithPaging(5, 'PageUp', 2000)).toBe(0);
    expect(nextIndexWithPaging(0, 'ArrowDown', 2000)).toBe(1);
    expect(nextIndexWithPaging(0, 'Tab', 2000)).toBeNull();
  });

  it('先頭で PageDown すると、11 行目が表示枠の下端に来る', () => {
    expect(scrollTopToReveal(10, 0, 40, 400)).toBe(40);
  });
});

describe('問題5：状態ごとの伝え方', () => {
  it('読み込み中は status + aria-busy', () => {
    expect(feedbackFor({ kind: 'loading' })).toEqual({ role: 'status', text: '商品を読み込んでいます', busy: true, action: null });
  });

  it('0 件は status で伝え、条件をクリアする操作を出す', () => {
    const f = feedbackFor({ kind: 'ready', count: 0, total: 2000, filtered: true });
    expect(f.role).toBe('status');
    expect(f.action).toBe('条件をクリア');
  });

  it('失敗は alert。読み込み失敗には再読み込みの操作を出す', () => {
    expect(feedbackFor({ kind: 'load-failed', status: 503 })).toMatchObject({ role: 'alert', action: 'もう一度読み込む' });
    expect(feedbackFor({ kind: 'save-failed', productName: '商品1' })).toMatchObject({ role: 'alert', action: null });
  });
});

describe('問題6：動きを減らす設定', () => {
  it('reduce なら smooth をやめて auto にする', () => {
    expect(scrollBehaviorFor(false)).toBe('smooth');
    expect(scrollBehaviorFor(true)).toBe('auto');
  });
});

describe('問題7：複数の行を DOM に残す', () => {
  it('範囲外・重複・負の番号を処理して番号順に返す', () => {
    const indices = renderIndicesMany(95, 115, [2, 2, 1999, -1, 2000], 2000);
    expect(indices).toHaveLength(22);
    expect(indices[0]).toBe(2);
    expect(indices[indices.length - 1]).toBe(1999);
  });

  it('範囲内の番号は増やさない', () => {
    expect(renderIndicesMany(0, 15, [0, 14], 2000)).toHaveLength(15);
  });
});
