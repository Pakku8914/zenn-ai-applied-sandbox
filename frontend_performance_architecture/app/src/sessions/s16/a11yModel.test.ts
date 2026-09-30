import { describe, expect, it } from 'vitest';
import { ApiError } from '../s10/fakeApi';
import {
  NO_MATCH_MESSAGE,
  formatCount,
  loadErrorMessage,
  nextIndex,
  renderIndices,
  resultMessage,
  scrollTopToReveal,
} from './a11yModel';
import { LIVE_DELAY_MS, createCatalogApi, loadCatalog, parseOptions } from './catalogApi';

const vertical = { orientation: 'vertical', wrap: false } as const;
const horizontal = { orientation: 'horizontal', wrap: true } as const;

describe('件数メッセージ（ライブリージョンの文）', () => {
  it('絞り込んでいなければ全件数、絞り込んだら見つかった件数を 3 桁区切りで返す', () => {
    expect(resultMessage(2000, 2000, false)).toBe('全 2,000 件を表示しています');
    expect(resultMessage(111, 2000, true)).toBe('111 件見つかりました');
    expect(resultMessage(1111, 2000, true)).toBe('1,111 件見つかりました');
    expect(formatCount(20000)).toBe('20,000');
  });

  it('0 件のときは、次に何をすればよいかまで伝える', () => {
    expect(resultMessage(0, 2000, true)).toBe(NO_MATCH_MESSAGE);
    expect(NO_MATCH_MESSAGE).toContain('キーワードを短くするか');
  });

  it('読み込み失敗の文は、ステータスと次の操作を含む', () => {
    expect(loadErrorMessage(503)).toBe('商品を読み込めませんでした（503）。通信状態を確認して「もう一度読み込む」を押してください。');
  });
});

describe('ロービングタブインデックスの移動先', () => {
  it('縦の一覧は ↑↓・Home・End で動き、端で止まる', () => {
    expect(nextIndex(0, 'ArrowDown', 2000, vertical)).toBe(1);
    expect(nextIndex(0, 'ArrowUp', 2000, vertical)).toBe(0);
    expect(nextIndex(1999, 'ArrowDown', 2000, vertical)).toBe(1999);
    expect(nextIndex(5, 'Home', 2000, vertical)).toBe(0);
    expect(nextIndex(5, 'End', 2000, vertical)).toBe(1999);
  });

  it('横のラジオグループは ←→ で動き、端で回り込む', () => {
    expect(nextIndex(0, 'ArrowRight', 5, horizontal)).toBe(1);
    expect(nextIndex(4, 'ArrowRight', 5, horizontal)).toBe(0);
    expect(nextIndex(0, 'ArrowLeft', 5, horizontal)).toBe(4);
  });

  it('扱わないキーと 0 件は null（preventDefault しない）', () => {
    expect(nextIndex(0, 'ArrowRight', 2000, vertical)).toBeNull();
    expect(nextIndex(0, 'ArrowDown', 5, horizontal)).toBeNull();
    expect(nextIndex(0, 'Enter', 2000, vertical)).toBeNull();
    expect(nextIndex(0, 'ArrowDown', 0, vertical)).toBeNull();
  });
});

describe('仮想化した一覧で DOM に置く行', () => {
  it('フォーカス中の行が表示範囲の中なら、範囲そのまま', () => {
    expect(renderIndices(0, 15, 0)).toHaveLength(15);
  });

  it('範囲の外なら 1 行だけ足し、番号順に並べる', () => {
    // scrollTop 4,000px の範囲は 95〜114 行目（S11）。フォーカスは 3 行目（index 2）に残っている
    const indices = renderIndices(95, 115, 2);
    expect(indices).toHaveLength(21);
    expect(indices[0]).toBe(2);
    expect(indices[1]).toBe(95);
  });
});

describe('行を表示枠に収める scrollTop', () => {
  it('上にはみ出したら行の上端、下にはみ出したら行の下端に合わせる', () => {
    expect(scrollTopToReveal(3, 4000, 40, 400)).toBe(120);
    expect(scrollTopToReveal(10, 0, 40, 400)).toBe(40);
    expect(scrollTopToReveal(1999, 0, 40, 400)).toBe(79600);
  });

  it('見えていれば動かさない', () => {
    expect(scrollTopToReveal(5, 0, 40, 400)).toBe(0);
  });
});

describe('ページの設定（クエリ文字列）と読み込み', () => {
  it('既定ではデバウンスあり・失敗なし', () => {
    expect(parseOptions('')).toEqual({ latencyMs: 300, failLoad: false, failFavorite: false, liveDelayMs: LIVE_DELAY_MS });
  });

  it('?latency・?fail・?live を読む。おかしな latency は既定値に戻す', () => {
    expect(parseOptions('?latency=10000&fail=load&fail=favorite&live=eager')).toEqual({
      latencyMs: 10000,
      failLoad: true,
      failFavorite: true,
      liveDelayMs: 0,
    });
    expect(parseOptions('?latency=abc').latencyMs).toBe(300);
  });

  it('failLoad なら 1 回目だけ 503 で失敗し、2 回目は 2,000 件を返す', async () => {
    const api = createCatalogApi({ ...parseOptions(''), latencyMs: 0 });
    const first = loadCatalog(api, { attempt: 0, failFirstAttempt: true });
    await expect(first).rejects.toBeInstanceOf(ApiError);
    await expect(first).rejects.toMatchObject({ status: 503 });
    await expect(loadCatalog(api, { attempt: 1, failFirstAttempt: true })).resolves.toHaveLength(2000);
  });
});
