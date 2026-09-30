import { useEffect, useState, type CSSProperties } from 'react';

/**
 * 少し遅れて文言が届くキャンペーンバナー。
 *   late     … 出題版。届いてから枠ごと差し込む（下の一覧が押し下げられる）
 *   reserved … 模範解答版。最初から同じ高さの枠を確保し、届いたら中身だけを入れる
 */
export type BannerMode = 'late' | 'reserved';

/** 文言が届くまでの時間（擬似）。measure/src/mid01 の CLS 計測はバナーの表示を待ってから読む */
export const CAMPAIGN_DELAY_MS = 300;
/** 商品写真つきのバナーを想定した高さ */
export const BANNER_HEIGHT_PX = 280;

const CAMPAIGN_TEXT = '今週末は送料無料。3,000 円以上のご注文が対象です。';

const bannerStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: BANNER_HEIGHT_PX,
  margin: '16px 0',
  padding: 24,
  borderRadius: 12,
  background: '#fef3c7',
  fontSize: 20,
};

export function CampaignBanner({ mode }: { mode: BannerMode }) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setText(CAMPAIGN_TEXT), CAMPAIGN_DELAY_MS);
    return () => clearTimeout(id);
  }, []);

  if (mode === 'reserved') {
    // 文言の有無にかかわらず高さは同じ。届いても周りは動かない
    return (
      <aside style={bannerStyle} data-campaign={text === null ? 'pending' : 'loaded'}>
        {text}
      </aside>
    );
  }
  // 文言が届くまで何も描かない。届いた瞬間に高さ 280px の枠が現れ、一覧を押し下げる
  if (text === null) {
    return null;
  }
  return (
    <aside style={bannerStyle} data-campaign="loaded">
      {text}
    </aside>
  );
}
