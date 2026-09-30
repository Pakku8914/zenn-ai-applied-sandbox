import { useEffect, useState } from 'react';
import { bannerStyle } from '../../shared/ui/styles';

export const CAMPAIGN_DELAY_MS = 300;
const CAMPAIGN_TEXT = '今週末は送料無料。3,000 円以上のご注文が対象です。';

/** キャンペーンバナー。文言が届く前から同じ高さの枠を置き、届いたら中身だけを入れる */
export function CampaignBanner() {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setText(CAMPAIGN_TEXT), CAMPAIGN_DELAY_MS);
    return () => clearTimeout(id);
  }, []);

  return (
    <aside style={bannerStyle} data-campaign={text === null ? 'pending' : 'loaded'}>
      {text}
    </aside>
  );
}
